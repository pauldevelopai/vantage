"""
On-demand live video relay (HLS) — the recording PC streams a camera to the
cloud ONLY while someone is watching it.

Flow:
  1. A viewer opens a camera in the console -> POST /watch (repeated as a
     heartbeat while the tab is open). This sets a short-lived "watch" flag.
  2. The recording agent polls the active watches. For each watched camera it
     runs one ffmpeg (RTSP -> H.264 HLS) and PUTs the playlist + segments here.
  3. The browser plays /hls/<camera>/index.m3u8 via hls.js.
  4. When the viewer leaves, the watch expires, the agent stops ffmpeg, and the
     bandwidth/CPU stop. Nothing runs when nobody is watching — economical.

This module only stores the small, ephemeral HLS files + the watch flags on
disk; it never touches the camera itself (only the agent, on the LAN, can).

Security: uploaded filenames are strictly validated (no path traversal; only
`.m3u8` / `.ts`), so an agent can't write outside its camera's directory.
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

WATCH_TTL_SECONDS = 12          # a watch stays active this long after each ping
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+\.(m3u8|ts)$")


def _safe_camera_id(camera_id: str) -> str:
    return "".join(c for c in (camera_id or "") if c.isalnum() or c in "-_")[:100]


def is_safe_hls_name(filename: str) -> bool:
    """Only bare `seg3.ts` / `index.m3u8` style names — no slashes, no `..`."""
    return bool(_SAFE_NAME.match(filename or ""))


class HlsRelay:
    def __init__(self, base_dir: str = "alibi/data/hls"):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.watch_file = self.base / "_watch.json"

    # -- watch signalling --------------------------------------------------- #

    def _load_watches(self) -> Dict[str, float]:
        try:
            return json.loads(self.watch_file.read_text() or "{}")
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_watches(self, watches: Dict[str, float]) -> None:
        tmp = self.watch_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(watches))
        tmp.replace(self.watch_file)

    def request_watch(self, camera_id: str, now: Optional[float] = None,
                      ttl: int = WATCH_TTL_SECONDS) -> float:
        """Mark a camera as being watched until now+ttl. Returns the expiry."""
        now = time.time() if now is None else now
        cid = _safe_camera_id(camera_id)
        watches = self._load_watches()
        expiry = now + ttl
        watches[cid] = expiry
        # opportunistically drop expired entries
        watches = {k: v for k, v in watches.items() if v > now}
        self._save_watches(watches)
        return expiry

    def active_watches(self, now: Optional[float] = None) -> List[str]:
        now = time.time() if now is None else now
        return sorted(cid for cid, exp in self._load_watches().items() if exp > now)

    def is_watched(self, camera_id: str, now: Optional[float] = None) -> bool:
        return _safe_camera_id(camera_id) in self.active_watches(now)

    # -- HLS files ---------------------------------------------------------- #

    def _cam_dir(self, camera_id: str) -> Path:
        d = self.base / _safe_camera_id(camera_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def put_file(self, camera_id: str, filename: str, data: bytes) -> bool:
        """Store an uploaded playlist/segment. Returns False on an unsafe name."""
        if not is_safe_hls_name(filename):
            return False
        path = self._cam_dir(camera_id) / filename
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return True

    def get_file(self, camera_id: str, filename: str) -> Optional[bytes]:
        if not is_safe_hls_name(filename):
            return None
        path = self.base / _safe_camera_id(camera_id) / filename
        try:
            return path.read_bytes()
        except OSError:
            return None

    def clear_camera(self, camera_id: str) -> None:
        """Drop a camera's HLS files (called when a stream stops)."""
        d = self.base / _safe_camera_id(camera_id)
        if d.exists():
            for f in d.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass


_relay: Optional[HlsRelay] = None


def get_hls_relay() -> HlsRelay:
    global _relay
    if _relay is None:
        _relay = HlsRelay()
    return _relay
