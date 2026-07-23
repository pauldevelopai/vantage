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


# ── how important is this, really? ──────────────────────────────────────
#
# The old scorer was a flat lookup table: at_vehicles = 65, dwell = 55, and so
# on, added up. That is rigid in three ways — the signals are coarse buckets,
# they only ever add (so a stranger who is ALSO after hours ALSO lingering is
# treated as three small things, not one worrying one), and nothing decays or
# reads the site's own rhythm.
#
# This is a multi-factor model instead. Each factor is CONTINUOUS in [0, 1]
# (how strong is this concern?), sharpened by real magnitudes when they exist —
# a ten-minute dwell scores higher than a two-minute one, a car seen once
# scores higher than one seen forty times. Factors combine by weight, then
# COMPOUND: several independent concerns occurring together lift the whole,
# because that is exactly what a real threat looks like. Fresh things weigh a
# little more than stale ones. And the weights live in one dict, so they can be
# tuned — or later learned from the confirmations the owner already makes —
# rather than being scattered constants.

# One place to tune. Higher = that concern matters more.
WEIGHTS: Dict[str, float] = {
    "flagged": 3.0,      # a hotlist plate / watchlist face — strongest auto signal
    "behaviour": 1.3,    # observed actions: at-vehicles, dwell, repeated passes
    "novelty": 0.9,      # how unfamiliar — a car barely ever here
    "stranger": 0.85,    # a person we cannot name
    "time": 0.7,         # how unusual the hour is for this site
    "severity": 0.6,     # the detector/VLM's own severity
}

# Each additional independent concern present lifts the total by this much —
# the compounding that makes co-occurring signals worth more than their sum.
CO_OCCURRENCE_LIFT = 0.25

# A human confirmation is not a factor to be weighed — it is ground truth, and
# sits above every computed score.
CONFIRMED_FLOOR = 100.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _hour_anomaly(ts: str, normal_hours: Optional[dict]) -> float:
    """How unusual is this time of day — for THIS site if we know its hours,
    else a smooth day/night curve. Continuous, not an after-hours flag."""
    try:
        hour = datetime.fromisoformat(str(ts).replace("Z", "")).hour
    except (ValueError, TypeError):
        return 0.3
    if normal_hours:
        start = int(normal_hours.get("start", 7))
        end = int(normal_hours.get("end", 21))
        inside = (start <= hour < end) if start <= end else (hour >= start or hour < end)
        return 0.15 if inside else 0.85
    # No site hours set: deep night is more notable than midday, smoothly.
    if 0 <= hour < 5 or hour >= 23:
        return 0.75
    if 5 <= hour < 7 or 21 <= hour < 23:
        return 0.45
    return 0.12


def _recency_weight(ts: str, now: datetime) -> float:
    """Fresh things weigh a little more; old ones decay toward a floor rather
    than to nothing, so a genuinely serious old alert is not buried."""
    try:
        age_h = max(0.0, (now - datetime.fromisoformat(str(ts).replace("Z", ""))).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return 1.0
    import math
    return 0.7 + 0.3 * math.exp(-age_h / 48.0)   # ~1.0 now, ~0.7 after days


def alert_factors(row: Dict[str, Any], normal_hours: Optional[dict] = None) -> Dict[str, float]:
    """The continuous [0,1] concern of each factor for this row. Pure and
    inspectable, so a card can show WHY it ranked where it did."""
    kind = row.get("kind", "")

    behaviour = {"at_vehicles": 1.0, "dwell": 0.85, "repeated_passes": 0.8,
                 "after_hours": 0.7, "out_of_ordinary": 0.65,
                 "new_vehicle": 0.5}.get(kind, 0.0)
    dwell_min = row.get("dwell_minutes")
    if isinstance(dwell_min, (int, float)):
        behaviour = max(behaviour, _clamp01(dwell_min / 10.0))   # 10 min = full
    passes = row.get("passes")
    if kind == "repeated_passes" and isinstance(passes, (int, float)):
        behaviour = max(behaviour, _clamp01(passes / 6.0))

    fam = row.get("familiarity")
    novelty = {"new": 0.8, "occasional": 0.5, "regular": 0.2,
               "resident": 0.0}.get(fam, 0.3 if fam is None else 0.0)
    if isinstance(passes, (int, float)):
        novelty = max(novelty, _clamp01(1.0 - passes / 20.0))    # 1 pass ≈ 0.95
    if row.get("owner_label"):
        novelty = min(novelty, 0.05)                             # you named it

    stranger = 0.0
    if row.get("event_type") == "person_detected":
        stranger = 0.0 if row.get("who") else 0.7

    return {
        "flagged": 1.0 if (row.get("hotlist_hit") or row.get("watchlist_hit")) else 0.0,
        "behaviour": behaviour,
        "novelty": novelty,
        "stranger": stranger,
        "time": _hour_anomaly(row.get("ts", ""), normal_hours),
        "severity": _clamp01(float(row.get("severity") or 0) / 5.0),
    }


def importance_score(row: Dict[str, Any], now: Optional[datetime] = None,
                     normal_hours: Optional[dict] = None) -> float:
    """A continuous, compounding, context-aware importance for one row."""
    if row.get("tier") == "confirmed":
        # Ground truth, plus its factors so two confirmed rows still order.
        f = alert_factors(row, normal_hours)
        return CONFIRMED_FLOOR + sum(WEIGHTS[k] * v for k, v in f.items())

    f = alert_factors(row, normal_hours)
    base = sum(WEIGHTS[k] * v for k, v in f.items())

    # Compounding: how many independent concerns are genuinely present. Several
    # weak-to-moderate signals together are the real shape of a threat.
    concerns = sum(1 for k in ("flagged", "behaviour", "novelty", "stranger", "time")
                   if f[k] >= 0.5)
    if concerns >= 2:
        base *= 1.0 + CO_OCCURRENCE_LIFT * (concerns - 1)

    # A person you have NAMED is not an alert for being present — "Paul is home"
    # is the opposite of a concern. Dampen hard when they are just here, and
    # only lightly when they are ALSO doing something worth a look (lingering at
    # 2am is worth noting whoever it is). A named car is routine the same way.
    known = bool(row.get("who")) or bool(row.get("owner_label"))
    if known:
        behaving = f["behaviour"] >= 0.5 or f["flagged"] >= 0.5
        base *= 0.7 if behaving else 0.25

    if row.get("tier") == "review":
        base += 0.8                                  # the system already flagged it

    base *= _recency_weight(row.get("ts", ""), now or datetime.utcnow())
    return base


def explain_score(row: Dict[str, Any], normal_hours: Optional[dict] = None) -> list:
    """The factors that drove this row's rank, strongest first — for showing a
    person why something is where it is, instead of an opaque number."""
    names = {"flagged": "flagged plate/face", "behaviour": "notable behaviour",
             "novelty": "unfamiliar", "stranger": "unidentified person",
             "time": "unusual hour", "severity": "high severity"}
    f = alert_factors(row, normal_hours)
    return [names[k] for k, v in sorted(f.items(), key=lambda kv: -kv[1]) if v >= 0.4]


def rank_alerts(rows: List[Dict[str, Any]], limit: int = 10,
                now: Optional[datetime] = None,
                normal_hours: Optional[dict] = None) -> List[Dict[str, Any]]:
    """The top `limit` things worth attention, worst first, each numbered.

    Scores EVERY row by the multi-factor model and keeps the highest, so the
    ten spots hold the ten most notable things. Each returned row gains a
    1-based `rank`, its `importance`, and a short `why`.
    """
    now = now or datetime.utcnow()
    scored = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    scored.sort(key=lambda r: importance_score(r, now, normal_hours), reverse=True)
    top = scored[:limit]
    for i, r in enumerate(top, 1):
        r["rank"] = i
        r["importance"] = round(importance_score(r, now, normal_hours), 2)
        r["why"] = explain_score(r, normal_hours)
    return top


def rank_situations(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Merge incident + criteria situation rows into the top-N worth attention.

    Every row needs `kind` (for priority) and `ts` (ISO, for recency). Rows keep
    their own `tier`. Sort by priority (kind), then newest first."""
    # Newest first, then a stable sort by priority so equal-priority rows keep
    # their recency order (Python's sort is stable).
    ordered = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    ordered.sort(key=lambda r: priority_of(r.get("kind", "")))
    return ordered[:limit]
