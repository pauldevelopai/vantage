"""
Situations — the "top things worth your attention right now", against criteria.

The Overview used to show a Situations panel that was only ever populated by
raised INCIDENTS. On a quiet site that panel sat empty even while the cameras
were seeing genuinely out-of-ordinary things — a car that isn't one of the usual
ones coming down the road, someone at the parked vehicles, presence after hours.

This module unifies every "worth a look" signal into ONE ranked list so the panel
reflects the site's real state, not just whether a formal incident fired:

  * out_of_ordinary_vehicles — from the recurring-vehicle clusters, keep the ones
    that are NOT the scene (new / occasional / unnamed) and say how often each
    came down the road and when. The usual cars (residents, regulars, owner-named)
    are excluded — that's the whole point of "out of the ordinary".
  * rank_situations — merge incident rows and criteria rows, order by how much
    they warrant attention (a human-confirmed incident first, a routine note
    last), newest first within a tier, and cap to the top N.

Honesty is preserved end-to-end: nothing here promotes a machine signal to
"confirmed" (only a person does that), and every criteria row is phrased "worth
a look", never as an accusation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from alibi.patterns.familiarity import classify_entity

VISIT_GAP_MINUTES = 10        # sightings this far apart belong to separate visits


def visit_count(timestamps: List[str], gap_minutes: int = VISIT_GAP_MINUTES) -> int:
    """How many distinct VISITS a run of sightings represents — the honest "how
    often it came down the road". A parked car re-detected every minute is ONE
    visit, not hundreds of sightings; a car that passes twice with hours between
    is two. A gap larger than `gap_minutes` starts a new visit. Pure."""
    parsed = []
    for t in timestamps or []:
        try:
            parsed.append(datetime.fromisoformat(str(t)[:19]))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return 0
    parsed.sort()
    gap = timedelta(minutes=gap_minutes)
    visits = 1
    for a, b in zip(parsed, parsed[1:]):
        if b - a > gap:
            visits += 1
    return visits

# Lower rank = higher up the list. A person's confirmation always wins; a routine
# "noted" incident always loses to a live criteria signal worth looking at.
PRIORITY: Dict[str, int] = {
    "confirmed": 0,
    "review": 1,
    "after_hours": 2,
    "at_vehicles": 3,
    "repeated_passes": 4,
    "dwell": 5,
    "new_vehicle": 6,
    "noted": 9,
}

def priority_of(kind: str) -> int:
    return PRIORITY.get(kind, 8)


def out_of_ordinary_vehicles(entities: List[Dict[str, Any]],
                             labels: Optional[Dict[str, Dict[str, Any]]] = None,
                             names: Optional[Dict[str, str]] = None,
                             visits_by_entity: Optional[Dict[str, int]] = None,
                             tz_offset_hours: int = 2, limit: int = 8,
                             now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The cars that are NOT the usual scene, with how often + when.

    `entities`: cross-camera vehicle entity summaries — each needs
    entity_id, count, first_seen, last_seen, days, active_hours, hours[24],
    cameras. Residents, regulars and owner-named vehicles are the scene and are
    excluded; what remains is new/occasional and unnamed.

    `visits_by_entity`: entity_id -> distinct VISITS (see visit_count). This is
    the honest "how often it came down the road"; the raw sighting `count` is
    motion-stills (a parked car makes hundreds) and is NOT surfaced as passes.
    Ordered new-first, then by visits."""
    labels = labels or {}
    names = names or {}
    visits_by_entity = visits_by_entity or {}
    rows: List[Dict[str, Any]] = []
    for e in entities:
        eid = e.get("entity_id")
        owner = (labels.get(eid) or {}).get("label")
        cls = classify_entity(int(e.get("count") or 0), e.get("first_seen") or "",
                              e.get("last_seen") or "", int(e.get("days") or 1),
                              int(e.get("active_hours") or 1), now=now)
        if owner or cls in ("resident", "regular"):
            continue                      # the usual cars — not out of the ordinary
        hours = e.get("hours") or [0] * 24
        busiest = hours.index(max(hours)) if any(hours) else None
        busiest_local = (busiest + tz_offset_hours) % 24 if busiest is not None else None
        passes = visits_by_entity.get(eid)
        rows.append({
            "entity_id": eid,
            "familiarity": cls,                       # "new" or "occasional"
            "passes": passes,                         # distinct visits (honest "how often")
            "sightings": int(e.get("count") or 0),    # raw motion-stills (not shown as passes)
            "days": int(e.get("days") or 1),
            "first_seen": e.get("first_seen"),
            "last_seen": e.get("last_seen"),
            "busiest_hour_local": busiest_local,      # when, in site-local time
            "cameras": [names.get(c, c) for c in (e.get("cameras") or [])],
        })
    order = {"new": 0, "occasional": 1}
    rows.sort(key=lambda r: (order.get(r["familiarity"], 2), -(r["passes"] or 0)))
    return rows[:limit]


def vehicle_descriptor(colour: Optional[str], body: Optional[str],
                       owner_label: Optional[str] = None) -> Optional[str]:
    """A real, human descriptor for a recurring vehicle instead of "Vehicle A".

    Priority: the owner's own name > what we can actually see (colour + body) >
    None (the caller shows the vehicle's photo + camera instead — a picture beats
    a letter). "unknown" colour and missing body are treated as not-known, never
    guessed."""
    if owner_label:
        return owner_label
    parts: List[str] = []
    c = (colour or "").strip().lower()
    if c and c != "unknown":
        parts.append(c.capitalize())
    b = (body or "").strip()
    if b:
        parts.append(b)
    return " ".join(parts) if parts else None


def rank_situations(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Merge incident + criteria situation rows into the top-N worth attention.

    Every row needs `kind` (for priority) and `ts` (ISO, for recency). Rows keep
    their own `tier`. Sort by priority (kind), then newest first."""
    # Newest first, then a stable sort by priority so equal-priority rows keep
    # their recency order (Python's sort is stable).
    ordered = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    ordered.sort(key=lambda r: priority_of(r.get("kind", "")))
    return ordered[:limit]
