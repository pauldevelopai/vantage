"""
Per-camera scene baseline — learning what is permanently in each view.

Every camera watches a scene that contains things. Paul's driveway camera has a
white SUV parked in it; his garden camera has shrubs the detector insists are a
car (0.6-0.7 confidence, every frame). Both are "vehicle = 1" forever. A system
that alerts on presence therefore alerts forever, and the owner stops looking —
the one failure a security product cannot survive.

A confidence threshold can't separate those two: the real SUV scores 0.794 and
the shrub 0.7. Nothing about the *detection* distinguishes them. What separates
them is **persistence**: both are always there, so neither is news. What IS news
is more than usual — a person where there is normally none, a second vehicle
beside the parked one.

So each camera learns its own normal:

    camera .91  ->  vehicle: normally 1   (the parked SUV)
    camera .92  ->  vehicle: normally 1   (the shrub)      person: normally 0

and an observation is newsworthy only when some class exceeds that normal. The
shrub and the SUV both fall silent — for the same reason, without us having to
know which is which — while a person walking up either one still raises.

"Normal" is the MEDIAN count over a rolling window, which is deliberately robust:
a handful of odd frames can't drag it, so one visitor doesn't teach the camera
that visitors are normal.

The baseline is persisted, because it is learned. Losing it on every deploy would
re-alert on the same furniture each restart.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_STORE_PATH = "alibi/data/scene_baselines.json"

# How many recent observations define "normal" for a camera.
DEFAULT_WINDOW = 60
# Below this, we know too little to call anything furniture — see `newsworthy`.
DEFAULT_MIN_FRAMES = 8


def _plural(word: str, n: int) -> str:
    """These reasons are shown to the owner, so "2 vehicles", not "2 vehicle"."""
    return word if n == 1 else word + "s"


def _median(values: List[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[len(s) // 2]


class SceneBaseline:
    """What each camera normally shows. Dependency-injected for tests."""

    def __init__(self, window: int = DEFAULT_WINDOW,
                 min_frames: int = DEFAULT_MIN_FRAMES,
                 storage_path: Optional[str] = DEFAULT_STORE_PATH,
                 loader: Optional[Callable] = None,
                 saver: Optional[Callable] = None):
        self.window = window
        self.min_frames = min_frames
        self.path = Path(storage_path) if storage_path else None
        self._loader = loader
        self._saver = saver
        # camera_id -> list of {class: count}, oldest first
        self._hist: Dict[str, List[Dict[str, int]]] = {}
        self._load()

    # -- persistence -------------------------------------------------------- #

    def _load(self) -> None:
        if self._loader is not None:
            self._hist = self._loader() or {}
            return
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text() or "{}")
            hist = raw.get("history") or {}
            self._hist = {c: [dict(o) for o in obs][-self.window:] for c, obs in hist.items()}
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            self._hist = {}

    def _save(self) -> None:
        if self._saver is not None:
            self._saver(self._hist)
            return
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"history": self._hist}))
            tmp.replace(self.path)
        except OSError:
            pass          # a baseline that can't persist still works in memory

    # -- learning ----------------------------------------------------------- #

    def observe(self, camera_id: str, composition: Dict[str, int]) -> None:
        """Record what this camera is showing now."""
        clean = {}
        for k, v in (composition or {}).items():
            try:
                clean[str(k)] = max(0, int(v))
            except (TypeError, ValueError):
                continue
        hist = self._hist.setdefault(camera_id, [])
        hist.append(clean)
        if len(hist) > self.window:
            del hist[:-self.window]
        self._save()

    def normal(self, camera_id: str) -> Dict[str, int]:
        """What this camera normally shows: the median count per class."""
        hist = self._hist.get(camera_id) or []
        if not hist:
            return {}
        classes = {k for obs in hist for k in obs}
        return {c: _median([obs.get(c, 0) for obs in hist]) for c in classes}

    def frames_seen(self, camera_id: str) -> int:
        return len(self._hist.get(camera_id) or [])

    def is_learned(self, camera_id: str) -> bool:
        return self.frames_seen(camera_id) >= self.min_frames

    # -- the judgement ------------------------------------------------------ #

    def newsworthy(self, camera_id: str, composition: Dict[str, int],
                   flagged: bool = False) -> Tuple[bool, str]:
        """Is this observation worth raising? Returns (verdict, reason).

        Does NOT learn — call `observe` for that, so a caller can decide whether a
        frame should teach the baseline.
        """
        comp = {str(k): int(v or 0) for k, v in (composition or {}).items()}
        if flagged:
            return True, "flagged (hotlist/watchlist) — never treated as scenery"
        if not any(v > 0 for v in comp.values()):
            return False, "nothing detected"

        norm = self.normal(camera_id)
        if not self.is_learned(camera_id):
            # Too early to call anything furniture. Anything present is news —
            # honest, and it's how the camera's normal gets established.
            present = [f"{k}={v}" for k, v in comp.items() if v > 0]
            return True, f"still learning this scene ({self.frames_seen(camera_id)}/{self.min_frames} frames): {', '.join(present)}"

        for cls, count in comp.items():
            usual = norm.get(cls, 0)
            if count > usual:
                if usual == 0:
                    return True, f"{cls} appeared — this camera normally shows none"
                return True, f"{count} {_plural(cls, count)} — more than the usual {usual}"

        usual_desc = ", ".join(f"{k}={v}" for k, v in sorted(norm.items()) if v > 0) or "an empty scene"
        return False, f"matches what this camera always shows ({usual_desc})"


_baseline: Optional[SceneBaseline] = None


def get_scene_baseline() -> SceneBaseline:
    global _baseline
    if _baseline is None:
        _baseline = SceneBaseline(
            window=int(os.environ.get("VANTAGE_BASELINE_WINDOW", DEFAULT_WINDOW)),
            min_frames=int(os.environ.get("VANTAGE_BASELINE_MIN_FRAMES", DEFAULT_MIN_FRAMES)),
        )
    return _baseline


def reset_scene_baseline() -> None:
    """Drop the in-memory instance (tests, or a deliberate relearn)."""
    global _baseline
    _baseline = None
