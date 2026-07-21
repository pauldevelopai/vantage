"""
Patterns API — exposes the Phase-2 pattern-detection engine over HTTP so the
Control Room can show it.

  GET /patterns/activity?window=24h            -> what's been happening
  GET /patterns/plate/{plate}/incidents        -> plate near which incidents
  GET /patterns/person-history/{sighting_id}   -> has this person appeared before

All read-only, auth-gated. Results are the engine dataclasses, serialised.
"""

from dataclasses import asdict

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from alibi.auth import get_current_user, User
from alibi.patterns.activity_patterns import ActivityPatterns
from alibi.patterns.co_occurrence import CoOccurrence
from alibi.patterns.person_history import PersonHistory
from alibi.watchlist.face_sighting_store import get_face_sighting_store
from alibi.vehicles.sightings_store import VehicleSightingsStore

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.get("/activity")
async def activity(window: str = "24h", current_user: User = Depends(get_current_user)):
    """Windowed activity summary (window = 1h | 24h | 7d | week | e.g. '3h')."""
    return asdict(ActivityPatterns().summarize(window))


@router.get("/plate/{plate}/incidents")
async def plate_incidents(
    plate: str,
    window_minutes: float = 30.0,
    current_user: User = Depends(get_current_user),
):
    """Incidents this plate was near (same camera, within the window)."""
    result = CoOccurrence().plate_incidents(plate, VehicleSightingsStore(), window_minutes)
    return asdict(result)


@router.get("/person-history/{sighting_id}")
async def person_history(
    sighting_id: str,
    threshold: float = 0.5,
    current_user: User = Depends(get_current_user),
):
    """Prior appearances of the person in a given face sighting."""
    store = get_face_sighting_store()
    match = next((s for s in store.load_all() if s.sighting_id == sighting_id), None)
    if not match or not match.embedding:
        raise HTTPException(status_code=404, detail="Face sighting not found or has no embedding")
    result = PersonHistory(match_threshold=threshold, store=store).look_up(
        np.array(match.embedding, dtype=np.float32), exclude_sighting_id=sighting_id
    )
    return asdict(result)


@router.get("/vehicle/{entity_id}")
async def vehicle_history(
    entity_id: str,
    window: str = "7d",
    frames_offset: int = 0,
    frames_limit: int = 12,
    current_user: User = Depends(get_current_user),
):
    """How often a recurring vehicle (an appearance-ReID cluster) has been seen
    over a window: total, per-day/per-hour breakdown, familiarity class, owner
    label if named, and the chronological trail. Continuity from our own
    cameras — never identity."""
    from datetime import datetime as _dt
    from alibi.cameras.cross_camera import get_cross_camera_tracker
    from alibi.patterns.familiarity import classify_entity, get_vehicle_labels

    hours = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}.get(window, 24 * 7)
    tracker = get_cross_camera_tracker()

    summary = next((e for e in tracker.entity_summary("vehicle", hours=hours)
                    if e["entity_id"] == entity_id), None)
    if summary is None:
        raise HTTPException(status_code=404,
                            detail="No sightings for this vehicle in the window")

    trail = tracker.get_entity_trail("vehicle", entity_id, hours=hours)

    # Real evidence photos + the plate: a representative frame, per-sighting frames
    # (from vehicle sightings by camera+second), and the most-read plate (from the
    # camera events — rare + noisy, so a majority vote).
    frame_url, bbox, colour, body, frames, plate, plate_region = None, None, None, None, [], None, None
    frames_total = 0
    try:
        from alibi.vehicles.evidence import (sightings_index, entity_evidence,
                                             trail_frames, trail_frames_total,
                                             plate_index, best_plate)
        from alibi.cameras import frame_notes
        idx = sightings_index()
        ev = entity_evidence(trail, idx)
        frame_url, bbox, colour, body = ev["frame_url"], ev["bbox"], ev["colour"], ev["body"]
        frames_total = trail_frames_total(trail, idx)
        frames = trail_frames(trail, idx, max_frames=max(1, min(int(frames_limit), 48)),
                              offset=max(0, int(frames_offset)))
        # Hang each snapshot's context off it: what the AI read in that frame and
        # anything the owner has written about it.
        for f in frames:
            fid = str(f.get("frame_url") or "").rsplit("/", 1)[-1].replace(".jpg", "")
            f["frame_id"] = fid
            ctx = frame_notes.get(fid) or {}
            f["description"] = ctx.get("description")
            f["note"] = ctx.get("note")
        try:
            from datetime import timedelta as _td
            from alibi.alibi_store import get_store
            pcut = _dt.utcnow() - _td(hours=hours)
            pev = [e for e in get_store().list_events(limit=8000)
                   if getattr(e, "ts", None) and e.ts >= pcut]
            bp = best_plate(trail, plate_index(pev))
            if bp:
                plate, plate_region = bp["plate"], bp["region"]
        except Exception:
            pass
    except Exception:
        pass

    # The name may be set directly on this cluster OR inherited from its plate, so
    # naming one appearance-fragment names every fragment that reads the plate.
    _row = get_vehicle_labels().get(entity_id) or {}
    label = _row.get("label")
    owner_details = _row.get("details")
    if plate:
        from alibi.patterns.familiarity import plate_labels, plate_details
        if not label:
            label = plate_labels().get(plate)
        if not owner_details:
            owner_details = plate_details().get(plate)
    # A vehicle the owner has CLAIMED is theirs is, by definition, part of the
    # scene — resident, regardless of how the raw maths would class this fragment.
    if label:
        cls = "resident"
    else:
        cls = classify_entity(summary["count"], summary["first_seen"], summary["last_seen"],
                              summary.get("days", 1), summary.get("active_hours", 1))

    # Per-day counts for a sparkline (site-local via UTC buckets).
    per_day: dict = {}
    for entry in trail:
        ts = entry.get("timestamp", "")[:10]
        if ts:
            per_day[ts] = per_day.get(ts, 0) + 1

    return {
        "entity_id": entity_id,
        "window": window,
        "owner_label": label,
        "owner_details": owner_details,
        "familiarity": cls,
        "count": summary["count"],
        "days": summary.get("days", 1),
        "first_seen": summary["first_seen"],
        "last_seen": summary["last_seen"],
        "cameras": summary["cameras"],
        "hours": summary["hours"],
        "colour": colour,
        "body": body,
        "plate": plate,               # most-read plate for this cluster (or null)
        "plate_region": plate_region,
        "frame_url": frame_url,
        "bbox": bbox,
        "frames": frames,      # ONE PAGE of appearances (newest first)
        "frames_total": frames_total,
        "frames_offset": max(0, int(frames_offset)),
        "per_day": [{"day": d, "count": n} for d, n in sorted(per_day.items())],
        "trail": [{"camera_id": e.get("camera_id"), "ts": e.get("timestamp")}
                  for e in trail],
    }
