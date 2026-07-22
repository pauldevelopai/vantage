"""
Familiar vs new — the system saying out loud what it understands about a scene.

Three pieces:
  * classify_entity  — is this recurring vehicle a RESIDENT (your own car), a
                       REGULAR (comes back on a rhythm), NEW to the scene, or
                       just occasional? Pure maths over its sighting record.
  * vehicle labels   — the owner can NAME a recurring vehicle ("Paul's Fortuner"),
                       exactly like enrolling a face: identity only ever comes
                       from the owner, never guessed.
  * pattern_findings — explicit, quotable sentences about what is happening:
                       "Vehicle A (your 'Fortuner') is here all the time — it's
                       part of the scene." / "Vehicle C is NEW — first seen 14:02."

Everything derives from our own cameras' sighting record. Situational language,
no accusations, no guessed identity.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

LABELS_FILE = Path("alibi/data/vehicle_labels.json")

NEW_WINDOW_HOURS = 24          # first seen within this = "new to the scene"
RESIDENT_MIN_DAYS = 3          # seen on this many distinct days = lives here
RESIDENT_MIN_HOURS_ACTIVE = 6  # ...OR across this many different hours of one day
RESIDENT_MIN_SIGHTINGS = 60    # ...OR this many sightings = a constant presence
REGULAR_MIN_DAYS = 2


def _passes(v: dict) -> str:
    """How many times it actually came past — passes, not frames.

    A parked car is detected in every frame, so the raw sighting count read
    "seen 4368x" for a vehicle that never moved. `visits` groups sightings
    separated by more than ten minutes; fall back to the raw count only for
    callers that predate it.
    """
    n = v.get("visits") or v.get("count") or 0
    return f"seen {n} time{'s' if n != 1 else ''}"


def classify_entity(count: int, first_seen: str, last_seen: str, days: int,
                    active_hours: int, now: Optional[datetime] = None) -> str:
    """resident | regular | new | occasional — from the sighting record alone.

    resident: the SCENE — a parked/constant vehicle. Recognised by PRESENCE, not
              tenure: seen across many hours of the day, OR with a high total
              sighting count. This is checked FIRST and deliberately: with only a
              day or two of data every ReID cluster's first sighting is recent, so
              without a persistence check a car seen 1000× in a day would be
              mislabeled "new" just because its cluster is young.
    new:      genuinely just appeared — first sighting within NEW_WINDOW_HOURS AND
              not already a constant presence.
    regular:  returns across several days in concentrated hours (the gardener, the
              school run) — a rhythm, not furniture.
    occasional: everything else (a rare visitor).
    """
    now = now or datetime.utcnow()
    try:
        first = datetime.fromisoformat(first_seen)
    except (ValueError, TypeError):
        first = now
    # Persistence FIRST — present all day, or seen a great many times = the scene.
    if active_hours >= RESIDENT_MIN_HOURS_ACTIVE or count >= RESIDENT_MIN_SIGHTINGS:
        return "resident"
    if (now - first) <= timedelta(hours=NEW_WINDOW_HOURS):
        return "new"
    if days >= REGULAR_MIN_DAYS:
        return "regular"
    return "occasional"


# ── Owner labels for recurring vehicles (the "that's MY car" button) ────────

def get_vehicle_labels() -> Dict[str, Dict[str, Any]]:
    try:
        if LABELS_FILE.exists():
            data = json.loads(LABELS_FILE.read_text())
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def set_vehicle_label(entity_id: str, label: str, set_by: str,
                      plate: Optional[str] = None,
                      details: Optional[str] = None,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """Name a recurring vehicle and record what the owner knows about it. Empty
    label removes the entry. A `plate`, when known, is stored with it so the name
    AND the details follow the PLATE across the appearance fragments the ReID
    clustering splits the same car into (see plate_labels / plate_details)."""
    labels = get_vehicle_labels()
    label = (label or "").strip()
    if label:
        row = {"label": label, "set_by": set_by,
               "set_at": (now or datetime.utcnow()).isoformat()}
        if plate:
            row["plate"] = str(plate).strip()
        d = (details or "").strip()[:2000]
        if d:
            row["details"] = d
        labels[entity_id] = row
    else:
        labels.pop(entity_id, None)
    LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LABELS_FILE.write_text(json.dumps(labels))
    return labels.get(entity_id) or {}


def plate_labels() -> Dict[str, str]:
    """{plate -> label} for every named vehicle that carried a plate — lets a name
    given to one cluster apply to any other cluster reading the same plate."""
    out: Dict[str, str] = {}
    for row in get_vehicle_labels().values():
        p = (row or {}).get("plate")
        if p and row.get("label"):
            out[str(p)] = row["label"]
    return out


def plate_details() -> Dict[str, str]:
    """{plate -> owner's notes} — the details follow the plate the same way the
    name does, so what you know about a car isn't stranded on one fragment."""
    out: Dict[str, str] = {}
    for row in get_vehicle_labels().values():
        p = (row or {}).get("plate")
        if p and (row or {}).get("details"):
            out[str(p)] = row["details"]
    return out


# ── Explicit pattern sentences ─────────────────────────────────────────────

_CLASS_PHRASE = {
    "resident": "here all the time — part of the scene",
    "regular": "comes back on a rhythm",
    "new": "NEW to the scene",
    "occasional": "seen occasionally",
}


def _hour_phrase(busiest_hour_local: Optional[int]) -> str:
    if busiest_hour_local is None:
        return ""
    return f", mostly around {busiest_hour_local:02d}:00"


def pattern_findings(vehicle_entities: List[Dict[str, Any]],
                     labels: Optional[Dict[str, Dict[str, Any]]] = None,
                     camera_normals: Optional[Dict[str, Dict[str, int]]] = None,
                     people_by_hour: Optional[List[int]] = None,
                     tz_offset_hours: int = 2,
                     now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Explicit sentences about what is happening, each with a kind so the UI
    can badge it. vehicle_entities rows need: label (display), entity_id, count,
    first_seen, last_seen, days, active_hours, busiest_hour_utc, cameras.

    Order: new arrivals first (that's what security wants to know), then
    regulars, then residents, then the always-there scene note."""
    labels = labels or {}
    findings: List[Dict[str, Any]] = []

    classed = []
    for v in vehicle_entities:
        cls = classify_entity(v["count"], v["first_seen"], v["last_seen"],
                              v.get("days", 1), v.get("active_hours", 1), now=now)
        classed.append((cls, v))

    order = {"new": 0, "regular": 1, "resident": 2, "occasional": 3}
    classed.sort(key=lambda cv: (order[cv[0]], -cv[1]["count"]))

    for cls, v in classed:
        owner = labels.get(v["entity_id"], {}).get("label")
        name = f"{v['label']}" + (f" (your “{owner}”)" if owner else "")
        busiest = v.get("busiest_hour_utc")
        busiest_local = (busiest + tz_offset_hours) % 24 if busiest is not None else None
        cams = ", ".join(v.get("cameras") or [])
        if cls == "new":
            try:
                first_t = datetime.fromisoformat(v["first_seen"]) + timedelta(hours=tz_offset_hours)
                first_txt = first_t.strftime("%H:%M")
            except (ValueError, TypeError):
                first_txt = "today"
            text = (f"{name} is NEW to the scene — first seen {first_txt} at {cams}, "
                    f"{_passes(v)} so far.")
        elif cls == "regular":
            text = (f"{name} keeps coming back — seen on {v.get('days', '?')} different days"
                    f"{_hour_phrase(busiest_local)} ({cams}). A pattern worth knowing about.")
        elif cls == "resident":
            text = (f"{name} is {_CLASS_PHRASE['resident']} — {_passes(v)} across "
                    f"{v.get('days', '?')} days at {cams}."
                    + ("" if owner else " If it's yours, name it and it stays quiet."))
        else:
            text = f"{name}: {_passes(v)} ({cams})."
        findings.append({"kind": cls, "entity_id": v["entity_id"], "label": v["label"],
                         "owner_label": owner, "text": text})

    # What each camera holds ALL the time — the learned scene itself.
    for cam, normal in (camera_normals or {}).items():
        parts = [f"{n} {k}{'s' if n != 1 else ''}" for k, n in normal.items() if n > 0]
        if parts:
            findings.append({
                "kind": "scene", "entity_id": None, "label": cam, "owner_label": None,
                "text": (f"{cam} normally shows {' and '.join(parts)} — the system treats "
                         f"that as the scene and only flags more than this."),
            })

    # When people usually appear (no identity — just the rhythm of the site).
    if people_by_hour and sum(people_by_hour) >= 3:
        busiest = people_by_hour.index(max(people_by_hour))
        findings.append({
            "kind": "people", "entity_id": None, "label": "People", "owner_label": None,
            "text": (f"People appear most often around "
                     f"{(busiest + tz_offset_hours) % 24:02d}:00 "
                     f"({sum(people_by_hour)} person events in this window)."),
        })
    return findings
