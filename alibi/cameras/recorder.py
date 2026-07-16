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
# ffmpeg's `scene` score is the FRACTION of the frame that changed, so useful
# surveillance motion is a small number: a person or vehicle entering frame scores
# roughly 0.01-0.05, while 0.4 is a hard scene cut (a channel change). The old
# 0.4 default meant the trigger essentially never fired — no motion stills, so no
# frames reached the cloud and the whole intelligence layer was starved.
# 0.02 catches a person/vehicle while ignoring sensor noise; the cloud throttles
# analysis to one frame per camera per 8s regardless, so erring low is cheap.
DEFAULT_MOTION_THRESHOLD = 0.02
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
    audio: bool = False,
    video_codec: Optional[str] = None,
) -> List[str]:
    """Continuous segmented recording. Video is always stream-copied (no
    re-encode → tiny CPU).

    `video_codec` is the probed source codec (see probe_video_codec). When the
    camera sends H.265, the copied track MUST be tagged `hvc1`: ffmpeg defaults to
    `hev1`, and QuickTime / Finder / Photos on macOS silently refuse to play an
    `hev1` MP4 (VLC plays either). Same bytes, one tag — this is the difference
    between a recording the owner can open and one they can't.

    Audio is OFF by default, for two reasons: (1) many cameras (Dahua etc.) send
    G.711 / PCM a-law, which MP4 cannot hold — copying it makes ffmpeg refuse to
    write the file; and (2) recording audio carries stricter legal obligations
    than video (e.g. RICA/POPIA in South Africa), so it should be a deliberate
    opt-in. When enabled, audio is transcoded to AAC so it fits the MP4 container.
    """
    audio_args = ["-c:a", "aac"] if audio else ["-an"]
    tag_args = ["-tag:v", "hvc1"] if str(video_codec or "").lower() in ("hevc", "h265") else []
    return [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-c:v", "copy",
        *tag_args,
        *audio_args,
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
    min_gap_seconds: float = 1.0,
) -> List[str]:
    """Write a JPEG only when the scene changes past `threshold` (= motion), and
    at most one per `min_gap_seconds`.

    ffmpeg does the detection via its scene filter, so the PC needs no CV libs.
    Point this at the low-res SUB stream to keep it cheap.

    The rate cap matters: `select` evaluates EVERY frame, so sustained motion on a
    15fps stream would otherwise write ~15 JPEGs a second — pointless disk churn
    and JPEG-encode CPU on the owner's PC, since the cloud only analyses one frame
    per camera per 8s anyway. `prev_selected_t` gives us the gap (isnan(...) lets
    the first frame through).
    """
    threshold = max(0.0, min(float(threshold), 1.0))
    gap = max(0.0, float(min_gap_seconds))
    # Normalize before the JPEG encoder: cameras often send full-range 4:2:0 HEVC
    # that ffmpeg's mjpeg encoder rejects ("Non full-range YUV is non-standard" /
    # encoder-init failure). `format=yuvj420p` gives it the JPEG-range pixels it
    # wants; capping width keeps frames small (cheap to store + upload); single
    # thread avoids the frame-thread encoder-init fault seen on some builds.
    gate = f"gt(scene,{threshold})"
    if gap > 0:
        # AND (*) a minimum gap since the previously selected frame; OR (+) the
        # very first frame, whose prev_selected_t is NaN.
        gate = f"({gate})*(isnan(prev_selected_t)+gte(t-prev_selected_t,{gap}))"
    vf = f"select='{gate}',scale='min(iw,640)':-2,format=yuvj420p"
    return [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-an",
        "-vf", vf,
        "-vsync", "vfr",
        "-threads", "1",
        "-q:v", "5",
        # -strftime expands the %Y%m%d… tokens (the image2 muxer needs this flag,
        # just like the segment muxer on the record job). One JPEG per motion
        # second; the timestamp is the filename, so frames are unique over time.
        "-strftime", "1",
        os.path.join(out_dir, f"{prefix}_%Y%m%d_%H%M%S.jpg"),
    ]


def probe_video_codec(url: str, run: Callable = subprocess.run, ffprobe: str = "ffprobe") -> Optional[str]:
    """Return the source video codec ('h264', 'hevc', …) via ffprobe, or None."""
    try:
        r = run([ffprobe, "-v", "error", "-rtsp_transport", "tcp",
                 "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                 "-of", "default=nk=1:nw=1", url],
                capture_output=True, text=True, timeout=15)
        return ((getattr(r, "stdout", "") or "").strip() or None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def has_encoder(name: str, ffmpeg: str = FFMPEG, run: Callable = subprocess.run) -> bool:
    """True if this ffmpeg build has the named encoder (e.g. h264_videotoolbox)."""
    try:
        r = run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10)
        return name in (getattr(r, "stdout", "") or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def choose_video_args(
    url: str, ffmpeg: str = FFMPEG, run: Callable = subprocess.run,
    max_width: int = 480, fps: int = 10, crf: int = 30,
    maxrate_kbps: int = 500, seg_seconds: int = 2,
) -> List[str]:
    """Pick the cheapest path to browser-playable H.264:
      * source already H.264  -> stream-COPY (no transcode, ~0 CPU);
      * else transcode, preferring a HARDWARE encoder (VideoToolbox / NVENC /
        QSV) over software libx264 — the difference between smooth and stutter.
    """
    codec = (probe_video_codec(url, run=run) or "").lower()
    if codec == "h264":
        return ["-c:v", "copy"]

    scale = ["-vf", f"scale='min(iw,{max_width})':-2", "-r", str(fps),
             "-pix_fmt", "yuv420p", "-g", str(max(1, fps * seg_seconds))]
    rate = ["-b:v", f"{maxrate_kbps}k", "-maxrate", f"{maxrate_kbps}k",
            "-bufsize", f"{maxrate_kbps * 2}k"]
    if has_encoder("h264_videotoolbox", ffmpeg, run):          # macOS hardware
        return ["-c:v", "h264_videotoolbox", "-realtime", "1", *rate, *scale]
    if has_encoder("h264_nvenc", ffmpeg, run):                 # NVIDIA
        return ["-c:v", "h264_nvenc", "-preset", "p3", *rate, *scale]
    if has_encoder("h264_qsv", ffmpeg, run):                   # Intel Quick Sync
        return ["-c:v", "h264_qsv", *rate, *scale]
    return ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-crf", str(crf), "-maxrate", f"{maxrate_kbps}k",
            "-bufsize", f"{maxrate_kbps * 2}k", *scale]


def build_hls_command(
    rtsp_url: str,
    out_dir: str,
    ffmpeg: str = FFMPEG,
    max_width: int = 480,
    seg_seconds: int = 4,
    list_size: int = 10,
    fps: int = 8,
    crf: int = 30,
    maxrate_kbps: int = 500,
    video_args: Optional[List[str]] = None,
) -> List[str]:
    """RTSP -> browser-playable HLS for on-demand live view.

    `video_args` selects the codec path (see choose_video_args): stream-copy for
    an H.264 source, or a hardware/software transcode for H.265. Defaults to the
    bandwidth-tuned software transcode if not supplied. Point at the SUB stream so
    the source is already low-res. Rolling live playlist; only runs while watched.
    """
    if video_args is None:
        video_args = [
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-crf", str(crf),
            "-maxrate", f"{maxrate_kbps}k", "-bufsize", f"{maxrate_kbps * 2}k",
            "-pix_fmt", "yuv420p", "-g", str(max(1, fps * seg_seconds)),
            "-r", str(fps),
            "-vf", f"scale='min(iw,{max_width})':-2",
        ]
    return [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-an",
        *video_args,
        "-f", "hls",
        "-hls_time", str(seg_seconds),
        "-hls_list_size", str(list_size),
        "-hls_flags", "delete_segments+append_list+omit_endlist",
        "-hls_segment_filename", os.path.join(out_dir, "seg%d.ts"),
        os.path.join(out_dir, "index.m3u8"),
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
        record_audio: bool = False,
        ffmpeg: str = FFMPEG,
        spawn: Callable = subprocess.Popen,
        clock: Callable[[], float] = None,
        video_codec: Optional[str] = None,
        probe: Optional[Callable] = None,
    ):
        self.camera_id = camera_id
        self.record_url = record_url
        self.motion_url = motion_url or record_url   # prefer the cheap sub-stream
        self.base_dir = base_dir
        self.segment_seconds = segment_seconds
        self.retention = retention
        self.motion_threshold = motion_threshold
        self.record_motion = record_motion
        self.record_audio = record_audio
        self.ffmpeg = ffmpeg
        self._spawn = spawn
        import time as _time
        self._clock = clock or _time.time
        self._jobs: List[_Job] = []
        # Source codec drives the MP4 tag (hvc1 for H.265 so macOS can play it).
        # Given explicitly => no probe; otherwise probed once, lazily, on start.
        self._record_codec = video_codec
        self._codec_probed = video_codec is not None
        self._probe = probe or probe_video_codec

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

    def _probe_record_codec(self) -> Optional[str]:
        """Probe the record stream's codec once, so an H.265 camera's recordings
        get the `hvc1` tag QuickTime needs. Never fatal: on a probe failure we
        just record untagged (as before)."""
        if not self._codec_probed:
            try:
                self._record_codec = self._probe(self.record_url)
            except Exception:
                self._record_codec = None
            self._codec_probed = True
        return self._record_codec

    def _build_jobs(self) -> List[_Job]:
        jobs = [_Job("record", build_record_command(
            self.record_url, self.recordings_dir,
            segment_seconds=self.segment_seconds,
            prefix=self.camera_id, ffmpeg=self.ffmpeg,
            audio=self.record_audio,
            video_codec=self._probe_record_codec(),
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
    p.add_argument("--audio", action="store_true", help="Record audio too (transcoded to AAC). Off by default — many cameras send MP4-incompatible audio, and audio recording has stricter legal duties than video.")
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
        record_audio=args.audio,
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
