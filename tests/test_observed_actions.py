"""
Observed actions around vehicles — honest, action-based flagging (pinned).

We flag a concrete VISIBLE action (a person at / moving between parked cars),
never intent guessed from appearance. The span under-reports by construction and
the language stays "worth a look", never accusatory.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from alibi.patterns.observed_actions import (
    _inside_halo, vehicle_contact_spans, detections_from_events, evaluate_at_vehicles,
)

BASE = datetime(2026, 7, 20, 8, 0, 0)


def _site(**kw):
    base = dict(camera_ids=["cam-a"])
    base.update(kw)
    return SimpleNamespace(**base)


def _event(ts, persons, vehicles, cam="cam-a", eid="e"):
    dets = ([{"class": "person", "bbox": b} for b in persons]
            + [{"class": "car", "bbox": b} for b in vehicles])
    return SimpleNamespace(camera_id=cam, ts=ts, event_id=eid,
                           metadata={"intel": {"detections": dets}})


# ── halo geometry ───────────────────────────────────────────────────────────

def test_person_at_car_door_is_inside_halo():
    # person box just left of the car, within the 0.4 halo
    assert _inside_halo([90, 100, 20, 60], [120, 100, 80, 50]) is True


def test_person_across_the_frame_is_not_at_the_car():
    assert _inside_halo([600, 100, 20, 60], [120, 100, 80, 50]) is False


# ── contact spans ───────────────────────────────────────────────────────────

def test_moving_between_several_vehicles_is_one_span_counting_each():
    # a person near three different parked cars over ~2 min at one camera
    dets = [
        {"camera_id": "cam-a", "ts": BASE, "persons": [[90, 100, 20, 60]],
         "vehicles": [[120, 100, 80, 50]]},
        {"camera_id": "cam-a", "ts": BASE + timedelta(seconds=60),
         "persons": [[290, 100, 20, 60]], "vehicles": [[320, 100, 80, 50]]},
        {"camera_id": "cam-a", "ts": BASE + timedelta(seconds=120),
         "persons": [[490, 100, 20, 60]], "vehicles": [[520, 100, 80, 50]]},
    ]
    spans = vehicle_contact_spans(dets)
    assert len(spans) == 1
    assert spans[0]["vehicles_touched"] == 3
    assert spans[0]["minutes"] == 2.0


def test_chain_breaks_after_gap():
    dets = [
        {"camera_id": "cam-a", "ts": BASE, "persons": [[90, 100, 20, 60]],
         "vehicles": [[120, 100, 80, 50]]},
        # 5 min later — a separate visit, its own span
        {"camera_id": "cam-a", "ts": BASE + timedelta(minutes=5),
         "persons": [[90, 100, 20, 60]], "vehicles": [[120, 100, 80, 50]]},
    ]
    spans = vehicle_contact_spans(dets)
    assert len(spans) == 2
    assert all(s["vehicles_touched"] == 1 for s in spans)


def test_no_person_near_any_vehicle_yields_nothing():
    dets = [{"camera_id": "cam-a", "ts": BASE, "persons": [[600, 100, 20, 60]],
             "vehicles": [[120, 100, 80, 50]]}]
    assert vehicle_contact_spans(dets) == []


# ── evaluator ───────────────────────────────────────────────────────────────

def test_evaluate_fires_on_several_vehicles():
    events = [
        _event(BASE, [[90, 100, 20, 60]], [[120, 100, 80, 50]]),
        _event(BASE + timedelta(seconds=60), [[290, 100, 20, 60]], [[320, 100, 80, 50]]),
    ]
    res = evaluate_at_vehicles(_site(), events)
    assert res["fired"] is True and res["vehicles_touched"] == 2
    assert "worth a look" in res["note"]
    assert "suspect" not in res["note"].lower()


def test_evaluate_quiet_on_single_passerby():
    # one person near one car for a single still — a passer-by, not a situation
    events = [_event(BASE, [[90, 100, 20, 60]], [[120, 100, 80, 50]])]
    assert evaluate_at_vehicles(_site(), events)["fired"] is False


def test_evaluate_respects_site_cameras():
    events = [
        _event(BASE, [[90, 100, 20, 60]], [[120, 100, 80, 50]], cam="elsewhere"),
        _event(BASE + timedelta(seconds=60), [[290, 100, 20, 60]], [[320, 100, 80, 50]],
               cam="elsewhere"),
    ]
    assert evaluate_at_vehicles(_site(), events)["fired"] is False


def test_detections_from_events_needs_both_person_and_vehicle():
    only_person = _event(BASE, [[10, 10, 20, 60]], [])
    only_vehicle = _event(BASE, [], [[120, 100, 80, 50]])
    assert detections_from_events([only_person, only_vehicle]) == []
