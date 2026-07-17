"""
"What this site watches for" — the posture's review triggers as an ARMED panel.

Not "crimes": we do not detect crimes and must never claim to. Each trigger is a
SITUATION from the site's posture. A trigger only reports "not seen" when a real
evaluator actually checked stored events; a trigger without an evaluator (or
without the data it needs, e.g. normal hours not set) is shown as armed-but-not-
evaluated — we never imply we checked and found nothing.

Evaluators today:
  * after-hours presence  — a person event outside the site's normal hours
                            (needs `normal_hours` set on the site; times are
                            interpreted in the site's timezone).
  * repeated passes       — the same face appearing several times within a short
                            window, from OUR OWN sighting archive (continuity,
                            not identity).
Dwell and stationary-vehicle triggers need track-level duration the still-frame
pipeline doesn't produce yet — they stay armed-but-not-evaluated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

AFTER_HOURS_MARKERS = ("outside normal hours", "closed hours", "after-hours")
REPEATED_PASS_MARKERS = ("repeated passes",)


def trigger_kind(trigger: str) -> Optional[str]:
    """Which evaluator (if any) can honestly judge this trigger text."""
    low = (trigger or "").lower()
    if any(m in low for m in AFTER_HOURS_MARKERS):
        return "after_hours"
    if any(m in low for m in REPEATED_PASS_MARKERS):
        return "repeated_passes"
    return None


def _to_local(ts: datetime, tz_name: str) -> datetime:
    """Stored event timestamps are naive UTC; normal hours are local."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name or "Africa/Johannesburg")
    except Exception:
        return ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(tz)


def _parse_hhmm(value: Any) -> Optional[int]:
    """'07:30' -> minutes since midnight, or None."""
    try:
        h, m = str(value).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


def _event_intel(ev) -> dict:
    return ((getattr(ev, "metadata", None) or {}).get("intel") or {})


def evaluate_after_hours(site, events) -> Dict[str, Any]:
    """Person presence outside the site's normal hours. Honest requirements:
    without `normal_hours` we cannot know what "after hours" means for this
    household — so the trigger stays not-evaluated with the reason attached."""
    open_m = _parse_hhmm((site.normal_hours or {}).get("open"))
    close_m = _parse_hhmm((site.normal_hours or {}).get("close"))
    if open_m is None or close_m is None or open_m == close_m:
        return {"evaluated": False, "fired": False,
                "note": "set the site's normal hours to arm this"}

    cams = set(site.camera_ids or [])
    newest = None
    for e in events:
        if cams and e.camera_id not in cams:
            continue
        i = _event_intel(e)
        is_person = (int(i.get("person_count") or 0) > 0
                     or e.event_type == "person_detected")
        if not is_person:
            continue
        local = _to_local(e.ts, site.timezone)
        minutes = local.hour * 60 + local.minute
        if open_m < close_m:
            outside = minutes < open_m or minutes >= close_m
        else:                                  # overnight "open" window (e.g. 18:00–06:00)
            outside = close_m <= minutes < open_m
        if outside and (newest is None or e.ts > newest.ts):
            newest = e
    if newest is None:
        return {"evaluated": True, "fired": False}
    return {"evaluated": True, "fired": True, "ts": newest.ts.isoformat(),
            "camera_id": newest.camera_id, "event_id": newest.event_id}


def evaluate_repeated_passes(site, sightings, window_minutes: int = 30,
                             min_count: int = 3,
                             match_threshold: float = 0.5) -> Dict[str, Any]:
    """The same face several times within a short window — continuity over our
    own archive, never identity. `sightings` is the (already time-bounded) list
    of FaceSightings to consider."""
    cams = set(site.camera_ids or [])
    rows = []
    for s in sightings or []:
        if cams and s.camera_id not in cams:
            continue
        e = np.asarray(s.embedding, dtype=np.float32).ravel()
        n = float(np.linalg.norm(e))
        if e.size == 0 or n == 0:
            continue
        try:
            ts = datetime.fromisoformat(s.ts)
        except (ValueError, TypeError):
            continue
        rows.append((ts, e / n, s))
    if not rows:
        return {"evaluated": True, "fired": False}

    rows.sort(key=lambda r: r[0])
    window = timedelta(minutes=window_minutes)
    dims = {r[1].shape[0] for r in rows}
    for dim in dims:
        sub = [r for r in rows if r[1].shape[0] == dim]
        mat = np.stack([r[1] for r in sub])
        for i, (ts_i, emb_i, s_i) in enumerate(sub):
            sims = mat @ emb_i
            hits = [j for j in np.flatnonzero(sims >= match_threshold)
                    if abs(sub[j][0] - ts_i) <= window]
            if len(hits) >= min_count:
                newest = max((sub[j] for j in hits), key=lambda r: r[0])
                return {"evaluated": True, "fired": True,
                        "ts": newest[0].isoformat(),
                        "camera_id": newest[2].camera_id,
                        "sighting_id": newest[2].sighting_id}
    return {"evaluated": True, "fired": False}


def evaluate_watching_for(site, events, face_sightings=None) -> Dict[str, Any]:
    """The armed panel for one site: every posture trigger, each honestly marked
    evaluated / fired / armed-but-not-yet-evaluated."""
    posture = site.posture()
    triggers: List[Dict[str, Any]] = []
    for text in posture.review_triggers:
        kind = trigger_kind(text)
        row: Dict[str, Any] = {"trigger": text, "kind": kind,
                               "evaluated": False, "fired": False}
        if kind == "after_hours":
            row.update(evaluate_after_hours(site, events))
        elif kind == "repeated_passes":
            row.update(evaluate_repeated_passes(site, face_sightings or []))
        else:
            row["note"] = "not yet evaluated"
        triggers.append(row)
    return {
        "site_id": site.site_id,
        "site_name": site.name,
        "subject_type": site.subject_type,
        "posture_label": posture.label,
        "triggers": triggers,
    }
