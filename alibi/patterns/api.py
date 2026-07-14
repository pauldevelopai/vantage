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
