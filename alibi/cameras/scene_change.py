"""
Is this a new thing happening, or the same thing still sitting there?

A camera watching a driveway sends a motion frame every ten or twenty seconds.
The detector finds the parked car in every one of them, and each frame became
its own event: one incident on the live box holds 223 "vehicle detected"
events over three hours, all of the same stationary car, each with its own
near-identical photograph. That is what fills an incident page with dozens of
copies of one picture, inflates "seen 1056 times" for a car that never moved,
and fills the disk with frames of nothing happening.

The detector is not wrong — the car IS there in all 223 frames. What was wrong
is treating continued presence as repeated arrival.

So: compare a frame's detections with the last event we raised for that camera.
If the same kinds of things are in the same places, this is a continuation, not
news. We stay quiet, apart from an occasional heartbeat so a long presence
still leaves a trace and an incident does not look abandoned.

Deliberately NOT suppressed: anything new entering the frame. A person walking
up to that parked car is exactly the event worth having, and the class check
below is what makes sure it survives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

# How much two boxes must overlap to count as "the same thing, unmoved".
# Generous: detector boxes jitter by a few pixels between frames even when
# nothing has moved at all.
SAME_PLACE_IOU = 0.5

# Even when nothing changes, say so this often — a car parked all day should
# leave a handful of marks, not 223 and not silence.
HEARTBEAT_MINUTES = 30


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union of two (x, y, w, h) boxes."""
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Fingerprint:
    """What was in a frame: each detection as (class, box)."""
    ts: datetime
    detections: List[Tuple[str, Tuple[float, float, float, float]]]

    @classmethod
    def of(cls, intel: Optional[dict], ts: datetime) -> "Fingerprint":
        out = []
        for d in ((intel or {}).get("detections") or []):
            box = d.get("bbox") or []
            if len(box) == 4:
                out.append((str(d.get("class") or "?"), tuple(float(v) for v in box)))
        return cls(ts=ts, detections=out)

    @property
    def classes(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for cls_, _box in self.detections:
            counts[cls_] = counts.get(cls_, 0) + 1
        return counts


def is_continuation(prev: Optional[Fingerprint], cur: Fingerprint,
                    iou_threshold: float = SAME_PLACE_IOU) -> bool:
    """True when `cur` shows the same things, still in the same places.

    False the moment anything is added, removed, or has moved — those are the
    frames worth raising.
    """
    if prev is None or not cur.detections:
        return False
    if prev.classes != cur.classes:
        return False                    # something arrived or left

    # Every current box must sit on top of a previous box of the same class.
    unmatched = list(prev.detections)
    for cls_, box in cur.detections:
        hit = None
        for i, (pcls, pbox) in enumerate(unmatched):
            if pcls == cls_ and iou(box, pbox) >= iou_threshold:
                hit = i
                break
        if hit is None:
            return False                # this one has moved
        unmatched.pop(hit)
    return True


def should_raise(prev: Optional[Fingerprint], cur: Fingerprint,
                 heartbeat_minutes: float = HEARTBEAT_MINUTES,
                 iou_threshold: float = SAME_PLACE_IOU) -> Tuple[bool, str]:
    """Should this frame become an event? Returns (raise_it, why).

    `why` is recorded on the event so a quiet stretch is explainable later.
    """
    if not is_continuation(prev, cur, iou_threshold):
        return True, "changed"
    if prev is not None and cur.ts - prev.ts >= timedelta(minutes=heartbeat_minutes):
        return True, "still-there"
    return False, "unchanged"


class SceneMemory:
    """The last event-worthy frame per camera. Small and in-memory: losing it
    on restart costs one extra event, never a missed one."""

    def __init__(self, heartbeat_minutes: float = HEARTBEAT_MINUTES,
                 iou_threshold: float = SAME_PLACE_IOU):
        self.heartbeat_minutes = heartbeat_minutes
        self.iou_threshold = iou_threshold
        self._last: Dict[str, Fingerprint] = {}

    def consider(self, camera_id: str, intel: Optional[dict],
                 ts: datetime) -> Tuple[bool, str]:
        cur = Fingerprint.of(intel, ts)
        raise_it, why = should_raise(self._last.get(camera_id), cur,
                                     self.heartbeat_minutes, self.iou_threshold)
        if raise_it:
            self._last[camera_id] = cur
        return raise_it, why


_memory: Optional[SceneMemory] = None


def get_scene_memory() -> SceneMemory:
    global _memory
    if _memory is None:
        _memory = SceneMemory()
    return _memory
