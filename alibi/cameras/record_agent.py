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
    from alibi.cameras.recorder import (
        CameraRecorder, RetentionPolicy, ffmpeg_available, build_hls_command,
    )
except ImportError:  # flat zipapp layout on the user's PC
    from recorder import (
        CameraRecorder, RetentionPolicy, ffmpeg_available, build_hls_command,
    )


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


class HlsStreamer:
    """On-demand live view: runs one ffmpeg (RTSP -> H.264 HLS) per *watched*
    camera and uploads the playlist + new segments to the cloud. Starts/stops
    with the viewer, so nothing runs when nobody is watching.

    Dependency-injected (spawn / upload / lister / reader / clock) so the
    start/stop/upload logic unit-tests without ffmpeg or a network."""

    def __init__(self, base_dir, upload, ffmpeg="ffmpeg", spawn=None,
                 lister=None, reader=None, clock=time.time):
        self.base_dir = base_dir
        self._upload = upload                      # upload(camera_id, filename, bytes)
        self.ffmpeg = ffmpeg
        import subprocess as _sp
        self._spawn = spawn or _sp.Popen
        self._lister = lister or (lambda d: os.listdir(d) if os.path.isdir(d) else [])
        self._reader = reader or (lambda p: open(p, "rb").read())
        self._clock = clock
        self._streams = {}                         # camera_id -> {proc, dir, sent}

    def _cam_dir(self, camera_id):
        return os.path.join(self.base_dir, camera_id)

    def sync(self, watched):
        """Start streams for newly-watched cameras, stop ones no longer watched."""
        wanted = {w["camera_id"]: w["url"] for w in (watched or []) if w.get("url")}
        for cid in list(self._streams):
            if cid not in wanted:
                self._stop(cid)
        for cid, url in wanted.items():
            if cid not in self._streams:
                self._start(cid, url)

    def _start(self, cid, url):
        d = self._cam_dir(cid)
        os.makedirs(d, exist_ok=True)
        proc = self._spawn(build_hls_command(url, d, ffmpeg=self.ffmpeg))
        self._streams[cid] = {"proc": proc, "dir": d, "sent": {}}

    def _stop(self, cid):
        s = self._streams.pop(cid, None)
        if not s:
            return
        proc = s.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except (OSError, ValueError):
                pass

    def pump(self):
        """Upload any playlist/segment files that changed since last time.
        The playlist (.m3u8) is re-sent whenever it changes; segments once."""
        for cid, s in self._streams.items():
            d = s["dir"]
            for name in self._lister(d):
                if not (name.endswith(".ts") or name.endswith(".m3u8")):
                    continue
                path = os.path.join(d, name)
                try:
                    stamp = os.path.getmtime(path)
                    size = os.path.getsize(path)
                except OSError:
                    continue
                key = (stamp, size)
                if s["sent"].get(name) == key:
                    continue                       # unchanged -> already uploaded
                try:
                    data = self._reader(path)
                except OSError:
                    continue
                if self._upload(cid, name, data):
                    s["sent"][name] = key

    def stop_all(self):
        for cid in list(self._streams):
            self._stop(cid)

    @property
    def active(self):
        return sorted(self._streams)


def hls_loop(streamer, fetch_watches, sleep, poll_seconds=2,
             should_run=lambda: True):
    """Drive an HlsStreamer: poll which cameras are watched, sync ffmpeg, upload
    segments. Runs on its own thread alongside the recorder loop."""
    while should_run():
        try:
            streamer.sync(fetch_watches())
            streamer.pump()
        except Exception as e:                     # never kill the thread
            print(f"[live] stream pump failed: {e}")
        sleep(poll_seconds)


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

    # --- on-demand live view (HLS) -------------------------------------- #
    def fetch_watches():
        status, body = ba._http("GET", "/api/cameras/bridge/watch-requests", headers=headers)
        return (body or {}).get("cameras", []) if status == 200 else []

    def upload_hls(camera_id, filename, data):
        url = ba.VANTAGE_URL.rstrip("/") + f"/api/cameras/bridge/hls/{camera_id}/{filename}"
        req = ba.urlrequest.Request(
            url, data=data, method="PUT",
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        try:
            with ba.urlrequest.urlopen(req, timeout=15):
                return True
        except Exception:
            return False

    import threading
    streamer = HlsStreamer(base_dir=os.path.join(args.dir, "_hls"), upload=upload_hls)
    threading.Thread(
        target=hls_loop, args=(streamer, fetch_watches, time.sleep),
        daemon=True,
    ).start()

    # --- LAN scan + heartbeat (unified: this one agent also does discovery) --- #
    # Reuse the proven scanner loop so "Find my cameras" works from this PC, and
    # so it reports online. poll_once() heartbeats when idle, scans on a job.
    def scan_loop():
        while True:
            try:
                if ba.poll_once(headers) == "unauthorized":
                    print("[agent] credentials rejected — re-pair the recorder.")
                    return
            except Exception as e:
                print(f"[agent] scan/heartbeat failed: {e}")
            time.sleep(getattr(ba, "POLL_SECONDS", 3))
    threading.Thread(target=scan_loop, daemon=True).start()

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
        streamer.stop_all()
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
