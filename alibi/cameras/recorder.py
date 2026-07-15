"""
Vantage edge recorder — 24/7 local recording + a cheap motion trigger.

This is the heart of the "capture everything, spend nothing when idle" model:
the always-on PC records continuously to its own disk (the *past* — free, so an
incident that happens while nobody is watching is still on tape), and a cheap
motion trigger surfaces the moments the cloud should actually look at.

Two ffmpeg jobs per camera, both dependency-free on the PC (no OpenCV/numpy):

  1. **Continuous recording** — `-c copy` segmented capture. Stream-copy means
     NO re-encode, so CPU stays tiny; a basic PC handles several cameras. The
     MAIN (high-res) stream goes to disk for evidence quality.

  2. **Motion trigger** — ffmpeg's own scene-change filter
     (`select='gt(scene,threshold)'`) writes a frame ONLY when the picture
     changes materially. ffmpeg does the motion detection; we ship no CV code.
     Runs on the SUB (low-res) stream, so it's cheap. Those frames are what
     later gets uploaded to the cloud for the heavy AI (phase 4).

Retention keeps disk bounded: a per-camera byte budget and/or a hard age cap,
oldest-deleted-first.

Everything here is stdlib-only and dependency-injectable (spawn / scan / remove
/ clock), so it unit-tests without a real ffmpeg or camera. The command builders
are pure; a real-hardware smoke test validates the ffmpeg invocations end-to-end.
"""

import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

FFMPEG = "ffmpeg"

# ffmpeg's scene score is 0..1; ~0.3–0.5 is "something meaningfully changed".
DEFAULT_MOTION_THRESHOLD = 0.4
DEFAULT_SEGMENT_SECONDS = 600          # 10-minute segments
_RESTART_BACKOFF_SECONDS = 10          # wait before relaunching a died ffmpeg


# --------------------------------------------------------------------------- #
# Pure command builders (no side effects) — unit-testable, agent-embeddable.
# --------------------------------------------------------------------------- #

def build_record_command(
    rtsp_url: str,
    out_dir: str,
    segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
    prefix: str = "cam",
    ffmpeg: str = FFMPEG,
) -> List[str]:
    """Continuous segmented recording, stream-copied (no re-encode)."""
    return [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(int(segment_seconds)),
        "-segment_format", "mp4",
        "-reset_timestamps", "1",
        "-strftime", "1",
        os.path.join(out_dir, f"{prefix}_%Y%m%d_%H%M%S.mp4"),
    ]


def build_motion_command(
    rtsp_url: str,
    out_dir: str,
    threshold: float = DEFAULT_MOTION_THRESHOLD,
    prefix: str = "cam",
    ffmpeg: str = FFMPEG,
) -> List[str]:
    """Write a JPEG only when the scene changes past `threshold` (= motion).

    ffmpeg does the detection via its scene filter, so the PC needs no CV libs.
    Point this at the low-res SUB stream to keep it cheap.
    """
    threshold = max(0.0, min(float(threshold), 1.0))
    return [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-vf", f"select='gt(scene,{threshold})'",
        "-vsync", "vfr",
        "-q:v", "5",
        os.path.join(out_dir, f"{prefix}_%Y%m%d_%H%M%S_%03d.jpg"),
    ]


def ffmpeg_available(ffmpeg: str = FFMPEG, run: Callable = subprocess.run) -> bool:
    """True if ffmpeg is callable on this PC."""
    try:
        res = run([ffmpeg, "-version"], capture_output=True, timeout=10)
        return getattr(res, "returncode", 1) == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


# --------------------------------------------------------------------------- #
# Retention — bound disk with an oldest-first sweep.
# --------------------------------------------------------------------------- #

@dataclass
class RetentionPolicy:
    max_bytes: Optional[int] = None          # per-camera disk budget for segments
    max_age_seconds: Optional[int] = None    # hard age cap regardless of size


@dataclass
class FileInfo:
    path: str
    size: int
    mtime: float


def plan_retention(files: Sequence[FileInfo], now: float, policy: RetentionPolicy) -> List[str]:
    """Return the paths to delete (oldest-first) to satisfy the policy.

    Age cap first (delete anything too old), then the byte budget (delete oldest
    until under budget). Pure: no filesystem access, so it's fully testable.
    """
    ordered = sorted(files, key=lambda f: f.mtime)   # oldest first
    to_delete: List[str] = []
    deleted = set()

    if policy.max_age_seconds is not None:
        for f in ordered:
            if now - f.mtime > policy.max_age_seconds:
                to_delete.append(f.path)
                deleted.add(f.path)

    if policy.max_bytes is not None:
        remaining = [f for f in ordered if f.path not in deleted]
        total = sum(f.size for f in remaining)
        for f in remaining:
            if total <= policy.max_bytes:
                break
            to_delete.append(f.path)
            deleted.add(f.path)
            total -= f.size

    return to_delete


def _scan_dir(path: str) -> List[FileInfo]:
    """Real filesystem scan of a directory into FileInfo (non-recursive)."""
    out: List[FileInfo] = []
    try:
        entries = os.listdir(path)
    except OSError:
        return out
    for name in entries:
        full = os.path.join(path, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if os.path.isfile(full):
            out.append(FileInfo(path=full, size=st.st_size, mtime=st.st_mtime))
    return out


# --------------------------------------------------------------------------- #
# CameraRecorder — manages the two ffmpeg jobs for one camera, resiliently.
# --------------------------------------------------------------------------- #

@dataclass
class _Job:
    name: str                       # "record" | "motion"
    command: List[str]
    proc: object = None             # Popen-like (has poll()/terminate())
    next_retry: float = 0.0
    restarts: int = 0


class CameraRecorder:
    """Runs continuous recording + the motion trigger for one camera, and
    restarts either ffmpeg job if it dies. Dependency-injectable for tests."""

    def __init__(
        self,
        camera_id: str,
        record_url: str,
        base_dir: str,
        motion_url: Optional[str] = None,
        segment_seconds: int = DEFAULT_SEGMENT_SECONDS,
        retention: Optional[RetentionPolicy] = None,
        motion_threshold: float = DEFAULT_MOTION_THRESHOLD,
        record_motion: bool = True,
        ffmpeg: str = FFMPEG,
        spawn: Callable = subprocess.Popen,
        clock: Callable[[], float] = None,
    ):
        self.camera_id = camera_id
        self.record_url = record_url
        self.motion_url = motion_url or record_url   # prefer the cheap sub-stream
        self.base_dir = base_dir
        self.segment_seconds = segment_seconds
        self.retention = retention
        self.motion_threshold = motion_threshold
        self.record_motion = record_motion
        self.ffmpeg = ffmpeg
        self._spawn = spawn
        import time as _time
        self._clock = clock or _time.time
        self._jobs: List[_Job] = []

    # -- directory layout --------------------------------------------------- #

    @property
    def recordings_dir(self) -> str:
        return os.path.join(self.base_dir, self.camera_id, "recordings")

    @property
    def motion_dir(self) -> str:
        return os.path.join(self.base_dir, self.camera_id, "motion")

    def _ensure_dirs(self) -> None:
        os.makedirs(self.recordings_dir, exist_ok=True)
        if self.record_motion:
            os.makedirs(self.motion_dir, exist_ok=True)

    def _build_jobs(self) -> List[_Job]:
        jobs = [_Job("record", build_record_command(
            self.record_url, self.recordings_dir,
            segment_seconds=self.segment_seconds,
            prefix=self.camera_id, ffmpeg=self.ffmpeg,
        ))]
        if self.record_motion:
            jobs.append(_Job("motion", build_motion_command(
                self.motion_url, self.motion_dir,
                threshold=self.motion_threshold,
                prefix=self.camera_id, ffmpeg=self.ffmpeg,
            )))
        return jobs

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        self._ensure_dirs()
        self._jobs = self._build_jobs()
        for job in self._jobs:
            job.proc = self._spawn(job.command)

    def poll(self, now: Optional[float] = None) -> dict:
        """Check each ffmpeg job; relaunch (with backoff) any that died.
        Returns a small status dict. Call this on a loop."""
        now = self._clock() if now is None else now
        status = {}
        for job in self._jobs:
            alive = job.proc is not None and job.proc.poll() is None
            if not alive and now >= job.next_retry:
                job.proc = self._spawn(job.command)
                job.restarts += 1
                job.next_retry = now + _RESTART_BACKOFF_SECONDS
                alive = True
            status[job.name] = {"alive": alive, "restarts": job.restarts}
        return status

    def apply_retention(
        self,
        now: Optional[float] = None,
        scan: Callable[[str], List[FileInfo]] = _scan_dir,
        remove: Callable[[str], None] = os.remove,
    ) -> List[str]:
        """Delete old segments/motion frames per policy. Returns deleted paths."""
        if not self.retention:
            return []
        now = self._clock() if now is None else now
        deleted: List[str] = []
        for d in (self.recordings_dir, self.motion_dir if self.record_motion else None):
            if not d:
                continue
            for path in plan_retention(scan(d), now, self.retention):
                try:
                    remove(path)
                    deleted.append(path)
                except OSError:
                    pass
        return deleted

    def stop(self) -> None:
        for job in self._jobs:
            if job.proc is not None and job.proc.poll() is None:
                try:
                    job.proc.terminate()
                except (OSError, ValueError):
                    pass

    def status(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "jobs": {
                job.name: {
                    "alive": job.proc is not None and job.proc.poll() is None,
                    "restarts": job.restarts,
                }
                for job in self._jobs
            },
        }


# --------------------------------------------------------------------------- #
# CLI — record one camera on this PC. Lets you test on real hardware today,
# before the cloud-orchestrated agent lands. stdlib only.
#   python -m alibi.cameras.recorder --record-url rtsp://user:pw@ip:554/... \
#          --dir ./vantage-rec --max-gb 200 --max-days 30
# --------------------------------------------------------------------------- #

def _parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(description="Vantage edge recorder — one camera.")
    p.add_argument("--record-url", required=True, help="RTSP URL of the MAIN stream (recorded to disk)")
    p.add_argument("--motion-url", default=None, help="RTSP URL of the SUB stream for motion (defaults to --record-url)")
    p.add_argument("--dir", default="./vantage-recordings", help="Base directory for recordings + motion frames")
    p.add_argument("--camera-id", default="cam1", help="Identifier used in filenames and subfolders")
    p.add_argument("--segment-seconds", type=int, default=DEFAULT_SEGMENT_SECONDS, help="Length of each recording segment")
    p.add_argument("--motion-threshold", type=float, default=DEFAULT_MOTION_THRESHOLD, help="Scene-change score 0..1 that counts as motion")
    p.add_argument("--no-motion", action="store_true", help="Record only; skip the motion trigger")
    p.add_argument("--max-gb", type=float, default=None, help="Disk budget for this camera (GB); oldest deleted first")
    p.add_argument("--max-days", type=float, default=None, help="Hard age cap (days) regardless of size")
    p.add_argument("--poll-seconds", type=int, default=15, help="How often to health-check ffmpeg + sweep retention")
    p.add_argument("--ffmpeg", default=FFMPEG, help="Path to the ffmpeg binary")
    return p.parse_args(argv)


def run_cli(argv=None) -> int:
    import time
    args = _parse_args(argv)

    if not ffmpeg_available(args.ffmpeg):
        print(f"[recorder] ffmpeg not found (tried '{args.ffmpeg}'). Install ffmpeg and retry.")
        return 2

    retention = None
    if args.max_gb is not None or args.max_days is not None:
        retention = RetentionPolicy(
            max_bytes=int(args.max_gb * 1024 ** 3) if args.max_gb is not None else None,
            max_age_seconds=int(args.max_days * 86400) if args.max_days is not None else None,
        )

    rec = CameraRecorder(
        camera_id=args.camera_id,
        record_url=args.record_url,
        motion_url=args.motion_url,
        base_dir=args.dir,
        segment_seconds=args.segment_seconds,
        retention=retention,
        motion_threshold=args.motion_threshold,
        record_motion=not args.no_motion,
        ffmpeg=args.ffmpeg,
    )
    rec.start()
    print(f"[recorder] recording '{args.camera_id}' → {rec.recordings_dir}")
    if not args.no_motion:
        print(f"[recorder] motion frames → {rec.motion_dir} (scene>{args.motion_threshold})")
    print("[recorder] Ctrl-C to stop.")

    try:
        while True:
            time.sleep(args.poll_seconds)
            rec.poll()
            deleted = rec.apply_retention()
            if deleted:
                print(f"[recorder] retention removed {len(deleted)} old file(s)")
    except KeyboardInterrupt:
        print("\n[recorder] stopping…")
    finally:
        rec.stop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_cli())
