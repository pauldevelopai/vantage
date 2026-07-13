"""
Helpers to read what an incident actually observed, from its events.

Kept deliberately conservative: we only report counts we can derive from real
event data (event types and any counts the detectors already attached in
metadata). We never guess.
"""

from typing import Optional, Tuple

from alibi.schemas import Incident


def latest_camera_and_ts(incident: Incident):
    """Return (camera_id, zone_id, timestamp) from the most recent event, or (None, None, created_ts)."""
    if not incident.events:
        return None, None, incident.created_ts
    latest = max(incident.events, key=lambda e: e.ts)
    return latest.camera_id, latest.zone_id, latest.ts


def observed_counts(incident: Incident) -> Tuple[int, int]:
    """
    Best-effort (person_count, vehicle_count) for this incident.

    Prefers explicit counts a detector attached in event.metadata; otherwise
    counts events by type. Returns (0, 0) if nothing is derivable.
    """
    person = 0
    vehicle = 0
    for e in incident.events:
        md = e.metadata or {}
        pc = md.get("person_count")
        vc = md.get("vehicle_count")
        if isinstance(pc, (int, float)):
            person = max(person, int(pc))
        elif "person" in e.event_type:
            person += 1
        if isinstance(vc, (int, float)):
            vehicle = max(vehicle, int(vc))
        elif "vehicle" in e.event_type or "plate" in e.event_type:
            vehicle += 1
    return person, vehicle


def threat_level_from_severity(incident: Incident) -> str:
    """Map max incident severity onto the baseline engine's threat vocabulary."""
    sev = incident.get_max_severity()
    if sev >= 5:
        return "critical"
    if sev >= 4:
        return "warning"
    if sev >= 3:
        return "caution"
    return "safe"


def location_hint(camera_id: Optional[str], zone_id: Optional[str]) -> str:
    """A lowercase string used to loosely match free-text location fields."""
    return " ".join(p for p in (camera_id or "", zone_id or "") if p).lower()
