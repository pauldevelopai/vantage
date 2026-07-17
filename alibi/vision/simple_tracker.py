"""
Dependency-free multi-object tracker — assigns identity to detections.

Why this exists: tracking was done by `ultralytics` (`model.track(...)`), which
runs ByteTrack internally and hands back boxes that already carry an `id`.
Ultralytics is **AGPL-3.0**, which is a problem for a commercial deployment, and
it was the last AGPL code on any live path — detection itself already moved to
D-FINE (Apache-2.0).

But detection and tracking are different jobs. D-FINE says "there is a person
here"; it does not say "this is the same person as last frame". That identity is
what rules and incidents need ("loitering" is meaningless without knowing it's one
person standing still, not thirty strangers).

So this does the one missing piece: greedy IoU association between the previous
frame's tracks and this frame's detections, which is ByteTrack's core idea minus
the Kalman motion model. That trade is deliberate:

  * our frames are motion-triggered stills seconds apart, not a 30fps video —
    a motion model predicting where a box will be 8 seconds later is worthless;
  * Kalman + Hungarian matching is a lot of machinery to get wrong quietly;
  * IoU association over seconds-apart frames is honest about what it can do.

It matches only within a class (a person never becomes a car) and retires tracks
that go unseen. Pure Python + stdlib: no numpy, no torch, no licence.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

BBox = Tuple[int, int, int, int]        # x, y, w, h


def iou(a: BBox, b: BBox) -> float:
    """Intersection over union of two (x, y, w, h) boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = x2 - x1, y2 - y1
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Detection:
    """One detection to be tracked. Backend-agnostic on purpose."""
    bbox: BBox
    confidence: float
    class_name: str
    class_id: int = 0
    zones: List[str] = field(default_factory=list)


@dataclass
class Track:
    track_id: int
    bbox: BBox
    confidence: float
    class_name: str
    class_id: int = 0
    zones: List[str] = field(default_factory=list)
    hits: int = 1                       # frames matched
    age: int = 0                        # frames since last seen
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"track_id": self.track_id, "bbox": list(self.bbox),
                "confidence": self.confidence, "class_name": self.class_name,
                "class_id": self.class_id, "zones": self.zones, "hits": self.hits}


class SimpleTracker:
    """Greedy IoU tracker. Deterministic and testable — no model, no network."""

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 3):
        self.iou_threshold = iou_threshold
        self.max_age = max_age          # frames a track may go unseen before retiring
        self.tracks: Dict[int, Track] = {}
        self._next_id = 1
        self.frame_count = 0

    def update(self, detections: List[Detection],
               timestamp: Optional[datetime] = None) -> Dict[int, Track]:
        """Associate detections with existing tracks; return the live tracks."""
        timestamp = timestamp or datetime.utcnow()
        self.frame_count += 1

        # Score every (track, detection) pair that could plausibly match, then take
        # them best-first. Greedy is enough here and stays deterministic.
        candidates = []
        for tid, tr in self.tracks.items():
            for di, det in enumerate(detections):
                if det.class_name != tr.class_name:
                    continue            # a person never becomes a car
                score = iou(tr.bbox, det.bbox)
                if score >= self.iou_threshold:
                    candidates.append((score, tid, di))
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

        matched_tracks: set = set()
        matched_dets: set = set()
        for score, tid, di in candidates:
            if tid in matched_tracks or di in matched_dets:
                continue
            det = detections[di]
            tr = self.tracks[tid]
            tr.bbox = det.bbox
            tr.confidence = det.confidence
            tr.zones = det.zones
            tr.hits += 1
            tr.age = 0
            tr.last_seen = timestamp
            matched_tracks.add(tid)
            matched_dets.add(di)

        # Unmatched detections are new things in the scene.
        for di, det in enumerate(detections):
            if di in matched_dets:
                continue
            tid = self._next_id
            self._next_id += 1
            self.tracks[tid] = Track(
                track_id=tid, bbox=det.bbox, confidence=det.confidence,
                class_name=det.class_name, class_id=det.class_id, zones=det.zones,
                first_seen=timestamp, last_seen=timestamp,
            )
            matched_tracks.add(tid)

        # Age out anything we didn't see this frame.
        for tid, tr in list(self.tracks.items()):
            if tid in matched_tracks:
                continue
            tr.age += 1
            if tr.age > self.max_age:
                del self.tracks[tid]

        return dict(self.tracks)

    def active(self, min_hits: int = 1) -> Dict[int, Track]:
        """Tracks seen enough times to be believed, and seen this frame."""
        return {tid: t for tid, t in self.tracks.items()
                if t.hits >= min_hits and t.age == 0}

    def reset(self) -> None:
        self.tracks.clear()
        self._next_id = 1
        self.frame_count = 0


def detections_from_gatekeeper(result: Dict[str, Any],
                               zones_for_point=None,
                               zones_config=None) -> List[Detection]:
    """Gatekeeper output (D-FINE or YOLO) -> Detections.

    The gatekeeper already normalises both backends to objects with
    .bbox / .confidence / .class_name, so this is the seam that lets tracking stop
    caring which detector produced the boxes.
    """
    out: List[Detection] = []
    for d in (result or {}).get("detections", []) or []:
        try:
            x, y, w, h = (int(v) for v in d.bbox)
        except (AttributeError, TypeError, ValueError):
            continue
        zones: List[str] = []
        if zones_config and zones_for_point:
            try:
                zones = zones_for_point((x + w / 2, y + h / 2), zones_config) or []
            except Exception:
                zones = []
        out.append(Detection(
            bbox=(x, y, w, h),
            confidence=float(getattr(d, "confidence", 0.0)),
            class_name=str(getattr(d, "class_name", "object")),
            class_id=int(getattr(d, "class_id", 0) or 0),
            zones=zones,
        ))
    return out
