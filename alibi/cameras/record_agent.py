"""
Vantage recording agent — runs on the always-on PC.

It pairs with the cloud exactly like the scanner bridge (one download, auto-pair,
outbound-only), then pulls its **record-targets** — the cameras it should record,
each with a resolved main (record) + sub (motion) RTSP URL — and manages one
`CameraRecorder` per camera: recording 24/7 to the PC's disk and running the
cheap motion trigger. It keeps the set in sync as cameras are added/removed, and
health-checks + applies retention on a loop.

Design goals:
  * The PC owner runs ONE thing and everything records — no URLs to type.
  * Self-contained on the PC: stdlib only, no OpenCV/numpy. Ships as a zipapp
    alongside `recorder.py` (+ the bridge connection helpers), so the import
    below works both in the repo (`alibi.cameras.recorder`) and in the flat
    zipapp layout (`recorder`).

The `RecordAgent` class is dependency-injected (recorder factory + clock) so the
sync/lifecycle logic unit-tests without a real ffmpeg, camera, or network.
"""

import os
import time

try:  # in-repo (tests, the cloud box)
    from alibi.cameras.recorder import CameraRecorder, RetentionPolicy, ffmpeg_available
except ImportError:  # flat zipapp layout on the user's PC
    from recorder import CameraRecorder, RetentionPolicy, ffmpeg_available


class RecordAgent:
    """Manages the set of CameraRecorders for one PC, synced to the cloud's
    record-target list."""

    def __init__(self, base_dir, retention=None, recorder_factory=None,
                 clock=time.time):
        self.base_dir = base_dir
        self.retention = retention
        self._recorders = {}        # camera_id -> CameraRecorder
        self._urls = {}             # camera_id -> (record_url, motion_url)
        self._clock = clock
        self._recorder_factory = recorder_factory or self._default_factory

    def _default_factory(self, target):
        return CameraRecorder(
            camera_id=target["camera_id"],
            record_url=target["record_url"],
            motion_url=target.get("motion_url"),
            base_dir=self.base_dir,
            retention=self.retention,
        )

    # -- sync the running set to the desired targets ------------------------ #

    def sync_targets(self, targets):
        """Start recorders for new cameras, stop removed ones, and restart any
        whose URL changed. Returns the current recording set."""
        wanted = {t["camera_id"]: t for t in (targets or []) if t.get("record_url")}

        for cam_id in list(self._recorders):
            if cam_id not in wanted:
                self._stop(cam_id)

        for cam_id, t in wanted.items():
            key = (t.get("record_url"), t.get("motion_url"))
            if cam_id not in self._recorders:
                self._start(cam_id, t)
            elif self._urls.get(cam_id) != key:      # credentials/URL changed
                self._stop(cam_id)
                self._start(cam_id, t)

        return {"recording": sorted(self._recorders)}

    def _start(self, cam_id, target):
        rec = self._recorder_factory(target)
        rec.start()
        self._recorders[cam_id] = rec
        self._urls[cam_id] = (target.get("record_url"), target.get("motion_url"))

    def _stop(self, cam_id):
        rec = self._recorders.pop(cam_id, None)
        self._urls.pop(cam_id, None)
        if rec is not None:
            rec.stop()

    # -- periodic health + retention ---------------------------------------- #

    def tick(self):
        """Restart any died ffmpeg jobs and sweep retention. Call on a loop."""
        for rec in self._recorders.values():
            rec.poll()
            rec.apply_retention()

    def stop_all(self):
        for cam_id in list(self._recorders):
            self._stop(cam_id)

    def status(self):
        return {"recording": sorted(self._recorders), "count": len(self._recorders)}


def run_loop(agent, fetch_targets, sleep, poll_seconds=15, refresh_seconds=60,
             clock=time.time, should_run=lambda: True):
    """Drive a RecordAgent: refresh targets every `refresh_seconds`, health-check
    every `poll_seconds`. `fetch_targets`/`sleep`/`clock` are injected so this is
    testable. `should_run` lets a test stop the loop deterministically."""
    last_refresh = 0.0
    while should_run():
        now = clock()
        if now - last_refresh >= refresh_seconds:
            try:
                targets = fetch_targets()
                agent.sync_targets(targets)
            except Exception as e:        # never die on a transient cloud error
                print(f"[record-agent] target refresh failed: {e}")
            last_refresh = now
        agent.tick()
        sleep(poll_seconds)


# --------------------------------------------------------------------------- #
# Standalone entrypoint — used inside the downloaded zipapp on the PC.
# Reuses the bridge connection helpers (register/auth/http) so there's one
# proven connection path. Not exercised by unit tests (it needs the network).
# --------------------------------------------------------------------------- #

def main(argv=None):  # pragma: no cover
    try:
        from alibi.cameras import bridge_agent as ba
    except ImportError:
        import bridge_agent as ba

    import argparse

    p = argparse.ArgumentParser(description="Vantage recording agent (always-on PC).")
    p.add_argument("--dir", default=os.environ.get("VANTAGE_REC_DIR", "./vantage-recordings"))
    p.add_argument("--max-gb", type=float, default=float(os.environ.get("VANTAGE_MAX_GB", "0")) or None)
    p.add_argument("--max-days", type=float, default=float(os.environ.get("VANTAGE_MAX_DAYS", "0")) or None)
    p.add_argument("--poll-seconds", type=int, default=15)
    p.add_argument("--refresh-seconds", type=int, default=60)
    args = p.parse_args(argv)

    if not ffmpeg_available():
        print("[record-agent] ffmpeg not found on this PC. Install ffmpeg and retry.")
        return 2

    creds = ba.load_creds() or ba.register(ba.PAIRING_CODE)
    if not creds:
        print("[record-agent] could not pair with Vantage — check the pairing code / URL.")
        return 3
    headers = {"X-Bridge-Id": creds["bridge_id"], "X-Bridge-Token": creds["token"]}

    def fetch_targets():
        # Goes through Caddy, which strips the /api prefix before the backend.
        # _http returns a (status, body) tuple.
        status, body = ba._http("GET", "/api/cameras/bridge/record-targets", headers=headers)
        if status != 200:
            return []
        return (body or {}).get("targets", [])

    retention = None
    if args.max_gb or args.max_days:
        retention = RetentionPolicy(
            max_bytes=int(args.max_gb * 1024 ** 3) if args.max_gb else None,
            max_age_seconds=int(args.max_days * 86400) if args.max_days else None,
        )

    agent = RecordAgent(base_dir=args.dir, retention=retention)
    print(f"[record-agent] paired as {creds['bridge_id']}; recording to {args.dir}")
    try:
        run_loop(agent, fetch_targets, time.sleep,
                 poll_seconds=args.poll_seconds, refresh_seconds=args.refresh_seconds)
    except KeyboardInterrupt:
        print("\n[record-agent] stopping…")
    finally:
        agent.stop_all()
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
