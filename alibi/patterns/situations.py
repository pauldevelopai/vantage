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

from datetime import datetime
from typing import Any, Dict, List, Optional

from alibi.patterns.familiarity import classify_entity

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

# Criteria kinds get the "review" tier so the panel shows them as cards worth a
# look; only real incidents can carry "confirmed"/"noted".
_CRITERIA_TIER = "review"


def priority_of(kind: str) -> int:
    return PRIORITY.get(kind, 8)


def out_of_ordinary_vehicles(entities: List[Dict[str, Any]],
                             labels: Optional[Dict[str, Dict[str, Any]]] = None,
                             names: Optional[Dict[str, str]] = None,
                             tz_offset_hours: int = 2, limit: int = 8,
                             now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The cars that are NOT the usual scene, with how often + when.

    `entities`: cross-camera vehicle entity summaries — each needs
    entity_id, count, first_seen, last_seen, days, active_hours, hours[24],
    cameras. Residents, regulars and owner-named vehicles are the scene and are
    excluded; what remains is new/occasional and unnamed. Ordered new-first,
    then by how often it was seen."""
    labels = labels or {}
    names = names or {}
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
        rows.append({
            "entity_id": eid,
            "familiarity": cls,                       # "new" or "occasional"
            "count": int(e.get("count") or 0),        # how often it came down the road
            "days": int(e.get("days") or 1),
            "first_seen": e.get("first_seen"),
            "last_seen": e.get("last_seen"),
            "busiest_hour_local": busiest_local,      # when, in site-local time
            "cameras": [names.get(c, c) for c in (e.get("cameras") or [])],
        })
    order = {"new": 0, "occasional": 1}
    rows.sort(key=lambda r: (order.get(r["familiarity"], 2), -r["count"]))
    return rows[:limit]


def new_vehicle_situations(ooo_vehicles: List[Dict[str, Any]],
                           min_count: int = 1) -> List[Dict[str, Any]]:
    """Turn the most notable out-of-ordinary vehicles into situation rows —
    a NEW car that has already come down the road more than once is worth a
    mention on its own, even with no incident."""
    out: List[Dict[str, Any]] = []
    for v in ooo_vehicles:
        if v["familiarity"] != "new" or v["count"] < min_count:
            continue
        when = (f", mostly around {v['busiest_hour_local']:02d}:00"
                if v.get("busiest_hour_local") is not None else "")
        cams = ", ".join(v.get("cameras") or []) or "the cameras"
        times = f"{v['count']} time{'s' if v['count'] != 1 else ''}"
        out.append({
            "kind": "new_vehicle",
            "tier": _CRITERIA_TIER,
            "entity_id": v["entity_id"],
            "incident_id": None,
            "event_id": None,
            "title": f"A vehicle that isn't one of the usual ones — seen {times}",
            "description": (f"Not a resident or regular here. Came past {cams} "
                            f"{times}{when}. Worth a look."),
            "camera_name": (v.get("cameras") or [None])[0],
            "ts": v.get("last_seen"),
            "snapshot_url": None,
            "count": v["count"],
            "confirmed": None,
        })
    return out


def rank_situations(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Merge incident + criteria situation rows into the top-N worth attention.

    Every row needs `kind` (for priority) and `ts` (ISO, for recency). Rows keep
    their own `tier`. Sort by priority (kind), then newest first."""
    # Newest first, then a stable sort by priority so equal-priority rows keep
    # their recency order (Python's sort is stable).
    ordered = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    ordered.sort(key=lambda r: priority_of(r.get("kind", "")))
    return ordered[:limit]
