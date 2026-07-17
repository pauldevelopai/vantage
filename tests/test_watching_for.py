"""
Watching-for panel — honest evaluation rules, pinned.

The panel must never imply "we checked and found nothing" for a trigger that
wasn't actually checked: no normal hours -> after-hours stays not-evaluated;
dwell/vehicle triggers (no evaluator yet) stay not-evaluated; and a fired
trigger points at the real event it fired on.
"""

from datetime import datetime
from types import SimpleNamespace

import numpy as np

from alibi.site_profile import SiteProfile
from alibi.patterns.watching_for import (
    evaluate_after_hours, evaluate_repeated_passes, evaluate_watching_for, trigger_kind,
)


def _site(**kw):
    base = dict(site_id="s1", name="My House", subject_type="home",
                timezone="Africa/Johannesburg",
                normal_hours={"open": "06:00", "close": "22:00"},
                camera_ids=["cam-a", "cam-b"])
    base.update(kw)
    return SiteProfile(**base)


def _event(ts, camera_id="cam-a", event_type="person_detected", people=1, eid="e1"):
    return SimpleNamespace(
        event_id=eid, camera_id=camera_id, ts=ts, event_type=event_type,
        metadata={"intel": {"person_count": people}},
    )


def test_trigger_kind_mapping():
    assert trigger_kind("presence at the perimeter outside normal hours") == "after_hours"
    assert trigger_kind("presence on the premises during closed hours") == "after_hours"
    assert trigger_kind("repeated passes of the property in a short window") == "repeated_passes"
    assert trigger_kind("extended dwell at an entry point without approaching the door") is None


def test_after_hours_requires_normal_hours():
    res = evaluate_after_hours(_site(normal_hours={}), [_event(datetime(2026, 7, 17, 1, 0))])
    assert res["evaluated"] is False and res["fired"] is False
    assert "normal hours" in res["note"]


def test_after_hours_fires_outside_local_hours():
    # 23:30 UTC = 01:30 SAST — outside 06:00–22:00
    ev = _event(datetime(2026, 7, 16, 23, 30), eid="night")
    res = evaluate_after_hours(_site(), [ev])
    assert res == {"evaluated": True, "fired": True, "ts": ev.ts.isoformat(),
                   "camera_id": "cam-a", "event_id": "night"}


def test_after_hours_quiet_inside_hours():
    # 10:00 UTC = 12:00 SAST — inside hours
    res = evaluate_after_hours(_site(), [_event(datetime(2026, 7, 17, 10, 0))])
    assert res == {"evaluated": True, "fired": False}


def test_after_hours_ignores_other_sites_cameras_and_vehicles():
    night = datetime(2026, 7, 16, 23, 30)
    events = [
        _event(night, camera_id="elsewhere"),                      # not this site
        _event(night, event_type="vehicle_detected", people=0),    # not a person
    ]
    assert evaluate_after_hours(_site(), events)["fired"] is False


def _sighting(sid, ts, emb, cam="cam-a"):
    return SimpleNamespace(sighting_id=sid, camera_id=cam, ts=ts, embedding=emb.tolist())


def test_repeated_passes_fires_on_same_face_in_window():
    rng = np.random.default_rng(5)
    person = rng.standard_normal(128).astype(np.float32)
    person /= np.linalg.norm(person)
    sightings = [
        _sighting("a", "2026-07-17T08:00:00", person),
        _sighting("b", "2026-07-17T08:10:00", person),
        _sighting("c", "2026-07-17T08:20:00", person),
    ]
    res = evaluate_repeated_passes(_site(), sightings)
    assert res["fired"] is True and res["sighting_id"] == "c"


def test_repeated_passes_quiet_when_spread_out_or_different_people():
    rng = np.random.default_rng(6)
    person = rng.standard_normal(128).astype(np.float32)
    person /= np.linalg.norm(person)
    spread = [
        _sighting("a", "2026-07-17T02:00:00", person),
        _sighting("b", "2026-07-17T08:00:00", person),
        _sighting("c", "2026-07-17T14:00:00", person),
    ]
    assert evaluate_repeated_passes(_site(), spread)["fired"] is False

    different = []
    for i in range(3):
        v = rng.standard_normal(128).astype(np.float32)
        different.append(_sighting(f"d{i}", "2026-07-17T08:00:00", v / np.linalg.norm(v)))
    assert evaluate_repeated_passes(_site(), different)["fired"] is False


def test_panel_marks_unevaluable_triggers_as_armed_only():
    """Dwell and stationary-vehicle triggers have no honest evaluator yet — the
    panel must say 'not yet evaluated', never 'not seen'."""
    panel = evaluate_watching_for(_site(normal_hours={}), events=[], face_sightings=[])
    assert panel["site_name"] == "My House"
    by_kind = {t["kind"]: t for t in panel["triggers"]}
    assert len(panel["triggers"]) == 4                       # home posture has 4
    # no normal hours -> after-hours NOT evaluated, with the reason
    assert by_kind["after_hours"]["evaluated"] is False
    # repeated passes ran (empty archive -> honestly quiet)
    assert by_kind["repeated_passes"]["evaluated"] is True
    assert by_kind["repeated_passes"]["fired"] is False
    # the two track-level triggers stay armed-only
    unevaluated = [t for t in panel["triggers"] if t["kind"] is None]
    assert len(unevaluated) == 2
    assert all(t["evaluated"] is False and t["note"] == "not yet evaluated" for t in unevaluated)
