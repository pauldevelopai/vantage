"""
Continued presence is not repeated arrival. Pinned.

Live on 2026-07-22: incident inc_20260719_165129_35f53ca8 held 223
"vehicle detected" events across three hours — every one the same parked car,
each with its own near-identical photograph. That is what put dozens of copies
of one picture on an incident page, and it is the same fault behind "seen 1056
times" for a car that never moved.

The risk in fixing it is the opposite failure: going so quiet that a real
arrival is swallowed. The suppression tests below matter less than the ones
that prove a person walking up to that parked car still raises an event.
"""

from datetime import datetime, timedelta

import pytest

from alibi.cameras import scene_change as sc


T0 = datetime(2026, 7, 19, 16, 51, 29)
CAR = (259, 347, 90, 175)


def _intel(*dets):
    return {"detections": [{"class": c, "bbox": list(b)} for c, b in dets]}


def _fp(ts, *dets):
    return sc.Fingerprint.of(_intel(*dets), ts)


# ── the flood ────────────────────────────────────────────────────────────

def test_the_same_parked_car_does_not_keep_making_news():
    prev = _fp(T0, ("car", CAR))
    later = _fp(T0 + timedelta(seconds=20), ("car", CAR))
    assert sc.is_continuation(prev, later)
    assert sc.should_raise(prev, later)[0] is False


def test_detector_jitter_is_not_movement():
    """Boxes wobble a few pixels between frames with nothing moving."""
    prev = _fp(T0, ("car", CAR))
    jittered = _fp(T0 + timedelta(seconds=20), ("car", (262, 350, 88, 172)))
    assert sc.is_continuation(prev, jittered)


def test_three_hours_of_a_parked_car_becomes_a_handful_of_events():
    """The actual incident: 223 frames over 3h1m, the car never moving."""
    memory = sc.SceneMemory()
    raised = 0
    for i in range(223):
        ts = T0 + timedelta(seconds=i * 49)          # ~3 hours
        fresh, _why = memory.consider("driveway", _intel(("car", CAR)), ts)
        raised += fresh
    assert raised <= 8, f"still flooding: {raised} events"
    assert raised >= 2, "went completely silent on a 3-hour presence"


# ── what must still get through ──────────────────────────────────────────

def test_a_person_arriving_at_the_parked_car_is_news():
    """The failure that would matter. Suppressing this to tidy the page would
    hide the one thing worth seeing."""
    prev = _fp(T0, ("car", CAR))
    arrives = _fp(T0 + timedelta(seconds=20), ("car", CAR), ("person", (300, 380, 40, 90)))
    assert not sc.is_continuation(prev, arrives)
    assert sc.should_raise(prev, arrives) == (True, "changed")


def test_the_car_leaving_is_news():
    prev = _fp(T0, ("car", CAR), ("person", (300, 380, 40, 90)))
    gone = _fp(T0 + timedelta(seconds=20), ("car", CAR))
    assert not sc.is_continuation(prev, gone)


def test_a_car_driving_past_is_news_every_time_it_moves():
    memory = sc.SceneMemory()
    raised = 0
    for i in range(6):
        box = (100 + i * 120, 300, 90, 175)          # crossing the frame
        fresh, _ = memory.consider("gate", _intel(("car", box)), T0 + timedelta(seconds=i * 3))
        raised += fresh
    assert raised == 6, "a moving car was mistaken for a parked one"


def test_a_second_car_arriving_beside_the_first_is_news():
    prev = _fp(T0, ("car", CAR))
    two = _fp(T0 + timedelta(seconds=20), ("car", CAR), ("car", (500, 340, 95, 170)))
    assert not sc.is_continuation(prev, two)


def test_a_different_camera_is_judged_on_its_own():
    memory = sc.SceneMemory()
    assert memory.consider("driveway", _intel(("car", CAR)), T0)[0] is True
    assert memory.consider("gate", _intel(("car", CAR)), T0)[0] is True


# ── heartbeat + edges ────────────────────────────────────────────────────

def test_a_long_stay_still_leaves_a_trace():
    prev = _fp(T0, ("car", CAR))
    much_later = _fp(T0 + timedelta(minutes=sc.HEARTBEAT_MINUTES + 1), ("car", CAR))
    assert sc.should_raise(prev, much_later) == (True, "still-there")


def test_the_first_frame_is_always_news():
    assert sc.should_raise(None, _fp(T0, ("car", CAR))) == (True, "changed")


def test_a_frame_with_no_detections_is_never_a_continuation():
    prev = _fp(T0, ("car", CAR))
    assert not sc.is_continuation(prev, _fp(T0 + timedelta(seconds=20)))


def test_iou_basics():
    assert sc.iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert sc.iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0
    assert sc.iou((0, 0, 0, 0), (0, 0, 10, 10)) == 0.0
    assert sc.iou(None, (0, 0, 10, 10)) == 0.0


def test_malformed_detections_are_ignored_not_fatal():
    fp = sc.Fingerprint.of({"detections": [{"class": "car"}, {"bbox": [1, 2]}]}, T0)
    assert fp.detections == []
    assert sc.Fingerprint.of(None, T0).detections == []
