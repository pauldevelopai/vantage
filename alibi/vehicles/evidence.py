"""
Link ReID vehicle clusters to real evidence photos.

The appearance-ReID tracker knows a vehicle only as a cluster of (camera,
timestamp) sightings — it stores no frame. But the vehicle-sightings store DOES
keep a snapshot + bbox per detection. Both are written in the same detection
pass, so they line up on (camera, second): that's the bridge that lets a
recurring/out-of-ordinary vehicle show a photo of the ACTUAL car instead of an
anonymous "Vehicle A".

Colour/body come along when the sighting carried them ("unknown" is treated as
not-known, never guessed); make/model stay absent (the classifier is a stub).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


def _second(ts: Any) -> str:
    # Normalise to "YYYY-MM-DD HH:MM:SS" so datetime values (str → space) and ISO
    # strings (T separator) key identically — without this, event timestamps
    # (datetimes) never line up with the ReID trail's ISO strings.
    return str(ts)[:19].replace("T", " ")


def sightings_index(store=None, limit: int = 5000) -> Dict[tuple, list]:
    """Build a {(camera_id, second): [VehicleSighting]} index once, so many
    entities can be resolved without re-reading the store."""
    if store is None:
        from alibi.vehicles.sightings_store import VehicleSightingsStore
        store = VehicleSightingsStore()
    idx: Dict[tuple, list] = {}
    for v in store.load_all(limit=limit):
        idx.setdefault((v.camera_id, _second(v.ts)), []).append(v)
    return idx


def entity_evidence(trail: List[Dict[str, Any]], index: Dict[tuple, list]) -> Dict[str, Any]:
    """A photo of the actual car + its colour/type, from the sightings that line
    up with this cluster's trail. `trail` rows are {camera_id, timestamp}."""
    cols: Counter = Counter()
    bodies: Counter = Counter()
    frame_url: Optional[str] = None
    bbox: Optional[list] = None
    for r in trail:
        for m in index.get((r.get("camera_id"), _second(r.get("timestamp"))), []):
            c = getattr(m, "color", None)
            if c and c != "unknown":
                cols[c] += 1
            md = getattr(m, "metadata", None) or {}
            b = md.get("det_class") or md.get("body")
            if b:
                bodies[b] += 1
            if frame_url is None and getattr(m, "snapshot_url", None) and getattr(m, "bbox", None):
                frame_url, bbox = m.snapshot_url, list(m.bbox)
    return {
        "frame_url": frame_url,
        "bbox": bbox,
        "colour": cols.most_common(1)[0][0] if cols else None,
        "body": bodies.most_common(1)[0][0] if bodies else None,
    }


def plate_index(events) -> Dict[tuple, list]:
    """Index the (rare) plate reads by (camera, second). Plates live on the camera
    EVENTS' intel, not on vehicle sightings, so this is the bridge to a cluster's
    trail. Reads are sparse and noisy — callers vote across them (see best_plate)."""
    idx: Dict[tuple, list] = {}
    for e in events:
        intel = ((getattr(e, "metadata", None) or {}).get("intel") or {})
        for p in intel.get("plates") or []:
            text = p.get("display") or p.get("text")
            if text:
                idx.setdefault((e.camera_id, _second(e.ts)), []).append(
                    {"plate": text, "region": p.get("region"),
                     "confidence": p.get("confidence")})
    return idx


# A plate is only worth showing when the OCR actually READ it — not when it saw
# something once and guessed. On these camera angles a single low-confidence pass
# is almost always wrong (SKK4 0288 at 0.65 read once, the plate reader's other
# read that second was a different string entirely). Better to show no plate and
# let the owner type it than to print a wrong one they then have to notice and
# fix. So require the winner to be read more than once, to be a clear majority of
# what was read, and to carry real confidence.
_MIN_PLATE_READS = 2
_MIN_PLATE_AGREEMENT = 0.6
_MIN_PLATE_CONFIDENCE = 0.80


def best_plate(trail: List[Dict[str, Any]], index: Dict[tuple, list]) -> Optional[Dict[str, Any]]:
    """The plate for a cluster — ONLY when it was genuinely read: seen more than
    once, agreed on, and confident. Otherwise None (never a one-off guess). The
    owner can always type the real plate in the edit modal, which is trusted over
    anything here."""
    reads: List[tuple] = []          # (plate, confidence)
    region_by: Dict[str, Any] = {}
    for r in trail:
        for p in index.get((r.get("camera_id"), _second(r.get("timestamp"))), []):
            reads.append((p["plate"], p.get("confidence")))
            if p.get("region"):
                region_by[p["plate"]] = p["region"]
    if not reads:
        return None
    votes: Counter = Counter(pl for pl, _ in reads)
    plate, n = votes.most_common(1)[0]
    total = len(reads)
    confs = [c for pl, c in reads if pl == plate and c is not None]
    best_conf = max(confs) if confs else 0.0
    if (n < _MIN_PLATE_READS or (n / total) < _MIN_PLATE_AGREEMENT
            or best_conf < _MIN_PLATE_CONFIDENCE):
        return None                  # read too flimsy to trust — show no plate
    return {"plate": plate, "region": region_by.get(plate),
            "reads": n, "confidence": best_conf}


def trail_frames(trail: List[Dict[str, Any]], index: Dict[tuple, list],
                 max_frames: int = 12, offset: int = 0) -> List[Dict[str, Any]]:
    """One page of per-sighting evidence frames (newest first) so the history view
    can show the car across its appearances — a human checks it with their eyes.
    Paged rather than truncated: see trail_frames_total for the full count."""
    rows: List[Dict[str, Any]] = []
    seen_keys = set()
    skipped = 0
    for r in sorted(trail, key=lambda x: str(x.get("timestamp") or ""), reverse=True):
        key = (r.get("camera_id"), _second(r.get("timestamp")))
        if key in seen_keys:
            continue
        for m in index.get(key, []):
            if getattr(m, "snapshot_url", None) and getattr(m, "bbox", None):
                seen_keys.add(key)
                if skipped < offset:
                    skipped += 1
                else:
                    rows.append({"ts": r.get("timestamp"), "camera_id": r.get("camera_id"),
                                 "frame_url": m.snapshot_url, "bbox": list(m.bbox)})
                break
        if len(rows) >= max_frames:
            break
    return rows


def trail_frames_total(trail: List[Dict[str, Any]], index: Dict[tuple, list]) -> int:
    """How many distinct appearances actually have a snapshot — so the UI can page
    honestly instead of silently cutting the list off."""
    seen_keys = set()
    for r in trail:
        key = (r.get("camera_id"), _second(r.get("timestamp")))
        if key in seen_keys:
            continue
        for m in index.get(key, []):
            if getattr(m, "snapshot_url", None) and getattr(m, "bbox", None):
                seen_keys.add(key)
                break
    return len(seen_keys)
