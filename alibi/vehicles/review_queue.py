"""
Make/model review queue + local-data loop.

The classifier is a stub and make/model comes from the VLM. To eventually train
a LOCAL classifier that fits the Southern African vehicle mix (US/EU models
misfire here), we need locally-labelled data — so every vehicle crop that earned
an attribute guess is logged here with the guess, and a human confirms or
corrects it. Confirmed rows become the training corpus.

Honest by construction:
  * The crop is a view of a frame we ALREADY store (frame_id + bbox) — no second
    image pipeline, no extra storage at rest.
  * This is a BACK-OFFICE surface. It never changes what the client sees on the
    Overview — that stays VLM-or-absent. The queue only gathers labels.
  * A record keeps the VLM's claim verbatim as `claimed`; the human's answer
    goes in `label`. We never overwrite the claim with a guess.

`build_review_item` (normalise/validate) is pure and unit-tested; the store is a
thin JSONL wrapper.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

STATUSES = ("pending", "confirmed", "rejected")


@dataclass
class ReviewItem:
    item_id: str
    ts: str
    camera_id: str
    frame_url: str                 # /api/cameras/frames/<id>.jpg
    bbox: List[int]                # [x, y, w, h] in the stored frame's pixels
    claimed: Dict[str, Any]        # the VLM's guess: colour/make/model/body/confidence
    plate_region: Optional[Dict[str, Any]] = None
    status: str = "pending"        # pending | confirmed | rejected
    label: Optional[Dict[str, Any]] = None   # the human's answer (gold)
    reviewed_by: Optional[str] = None
    reviewed_ts: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReviewItem":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


def build_review_item(camera_id: str, frame_url: str, bbox: Any,
                      claimed: Dict[str, Any],
                      plate_region: Optional[Dict[str, Any]] = None,
                      ts: Optional[str] = None,
                      now: Optional[datetime] = None) -> Optional[ReviewItem]:
    """Normalise an ingest-time vehicle guess into a queue item, or None if it
    can't make a usable crop (no frame or bad bbox — nothing to review)."""
    now = now or datetime.utcnow()
    if not frame_url:
        return None
    try:
        box = [int(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    if len(box) != 4 or box[2] <= 0 or box[3] <= 0:
        return None
    claimed = {k: claimed.get(k) for k in ("colour", "make", "model", "body", "confidence")} if claimed else {}
    return ReviewItem(
        item_id=uuid.uuid4().hex[:16],
        ts=ts or now.isoformat(),
        camera_id=camera_id,
        frame_url=frame_url,
        bbox=box,
        claimed=claimed,
        plate_region=plate_region,
    )


def apply_review(item: ReviewItem, decision: str, reviewer: str,
                 label: Optional[Dict[str, Any]] = None,
                 now: Optional[datetime] = None) -> ReviewItem:
    """Record a human decision. 'confirm' accepts the VLM claim as the label (or
    a supplied correction); 'reject' marks it not-a-vehicle/unusable. Pure."""
    now = now or datetime.utcnow()
    if decision == "confirm":
        gold = label or {k: item.claimed.get(k) for k in ("colour", "make", "model", "body")}
        item.label = {k: (str(v).strip() or None) if v else None for k, v in gold.items()}
        item.status = "confirmed"
    elif decision == "reject":
        item.label = None
        item.status = "rejected"
    else:
        raise ValueError("decision must be 'confirm' or 'reject'")
    item.reviewed_by = reviewer
    item.reviewed_ts = now.isoformat()
    return item


class ReviewQueueStore:
    def __init__(self, storage_path: str = "alibi/data/vehicle_review_queue.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _all(self) -> List[ReviewItem]:
        if not self.storage_path.exists():
            return []
        items: Dict[str, ReviewItem] = {}
        for line in self.storage_path.read_text().splitlines():
            try:
                d = json.loads(line)
                items[d["item_id"]] = ReviewItem.from_dict(d)   # last write wins
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return list(items.values())

    def add(self, item: ReviewItem) -> None:
        with open(self.storage_path, "a") as f:
            f.write(json.dumps(item.to_dict()) + "\n")

    def get(self, item_id: str) -> Optional[ReviewItem]:
        return next((i for i in self._all() if i.item_id == item_id), None)

    def update(self, item: ReviewItem) -> None:
        self.add(item)                 # append-only; _all() keeps the latest

    def list_pending(self, limit: int = 50) -> List[ReviewItem]:
        items = [i for i in self._all() if i.status == "pending"]
        items.sort(key=lambda i: i.ts, reverse=True)
        return items[:limit]

    def counts(self) -> Dict[str, int]:
        c = {s: 0 for s in STATUSES}
        for i in self._all():
            c[i.status] = c.get(i.status, 0) + 1
        return c

    def confirmed_labels(self) -> List[Dict[str, Any]]:
        """The local-training corpus: confirmed crops + gold labels."""
        return [{"frame_url": i.frame_url, "bbox": i.bbox, "label": i.label,
                 "camera_id": i.camera_id, "ts": i.ts}
                for i in self._all() if i.status == "confirmed" and i.label]


_store: Optional[ReviewQueueStore] = None


def get_review_queue_store() -> ReviewQueueStore:
    global _store
    if _store is None:
        _store = ReviewQueueStore()
    return _store


def enqueue_vehicle_guess(intel, vehicles, camera_id: str, frame_id: str,
                          now: Optional[datetime] = None) -> int:
    """Ingest hook: log a review item when a single detected vehicle pairs with a
    single VLM description (the same unambiguous pairing the sighting write uses)
    — that's the only case where the crop and the guess reliably belong together.
    Never raises. Returns how many enqueued (0 or 1)."""
    try:
        dets = [d for d in ((intel or {}).get("detections") or [])
                if d.get("class") in ("car", "truck", "bus", "motorcycle")]
        vehicles = vehicles or []
        if len(dets) != 1 or len(vehicles) != 1:
            return 0
        item = build_review_item(
            camera_id=camera_id,
            frame_url=f"/api/cameras/frames/{frame_id}.jpg",
            bbox=dets[0].get("bbox"),
            claimed=vehicles[0],
            now=now,
        )
        if item is None:
            return 0
        get_review_queue_store().add(item)
        return 1
    except Exception as e:  # pragma: no cover
        print(f"[review-queue] enqueue failed: {e}")
        return 0
