"""
Security cares about CHANGE, not presence.

Real-world proof this exists: a white SUV parked on the driveway was correctly
detected in every single frame, so a presence-based rule raised "vehicle detected"
every few seconds, all night. Furniture must go quiet; arrivals must not.
"""

from datetime import datetime

from alibi.cameras.frame_analyzer import (
    decide_event, is_new_activity, reset_activity_baseline,
)

NOW = datetime(2026, 7, 16, 20, 0, 0)


def setup_function():
    reset_activity_baseline()


def _r(desc="", safety=False):
    return {"detected_objects": [], "description": desc, "confidence": 0.8, "safety_concern": safety}


# --- is_new_activity -------------------------------------------------------- #

def test_parked_car_goes_quiet_after_the_first_frame():
    assert is_new_activity("cam1", 0, 1) is True      # it arrived — news
    assert is_new_activity("cam1", 0, 1) is False     # still parked — furniture
    assert is_new_activity("cam1", 0, 1) is False


def test_a_person_arriving_beside_the_parked_car_is_news():
    is_new_activity("cam1", 0, 1)                     # car parked
    is_new_activity("cam1", 0, 1)                     # quiet
    assert is_new_activity("cam1", 1, 1) is True      # someone walks in -> news


def test_a_second_car_arriving_is_news():
    is_new_activity("cam1", 0, 1)
    assert is_new_activity("cam1", 0, 2) is True


def test_leaving_is_not_an_alert_but_rearming_works():
    is_new_activity("cam1", 1, 0)                     # person arrives
    assert is_new_activity("cam1", 0, 0) is False     # they leave — not an alert
    assert is_new_activity("cam1", 1, 0) is True      # someone arrives again — news


def test_empty_scene_is_never_news():
    assert is_new_activity("cam1", 0, 0) is False


def test_flagged_always_passes_even_if_unchanged():
    is_new_activity("cam1", 0, 1)
    assert is_new_activity("cam1", 0, 1, flagged=True) is True   # hotlist is never furniture


def test_baseline_is_per_camera():
    assert is_new_activity("cam1", 0, 1) is True
    assert is_new_activity("cam2", 0, 1) is True     # different camera, own baseline


# --- through decide_event --------------------------------------------------- #

def test_static_scene_stops_raising_incidents():
    intel = {"person_count": 0, "vehicle_count": 1}
    first = decide_event(_r("a car on the driveway"), "cam1", NOW, "f1", intel=intel)
    assert first is not None                          # the arrival
    again = decide_event(_r("a car on the driveway"), "cam1", NOW, "f2", intel=intel)
    assert again is None                              # the same parked car — silence


def test_person_arriving_still_raises_despite_static_car():
    car = {"person_count": 0, "vehicle_count": 1}
    decide_event(_r(), "cam1", NOW, "f1", intel=car)
    decide_event(_r(), "cam1", NOW, "f2", intel=car)
    ev = decide_event(_r(), "cam1", NOW, "f3", intel={"person_count": 1, "vehicle_count": 1})
    assert ev is not None and ev.event_type == "person_detected"


def test_hotlist_still_raises_on_an_unchanged_scene():
    intel = {"person_count": 0, "vehicle_count": 1, "hotlist_hit": True}
    decide_event(_r(), "cam1", NOW, "f1", intel=intel)
    ev = decide_event(_r(), "cam1", NOW, "f2", intel=intel)
    assert ev is not None and ev.severity == 4        # never suppressed


def test_vlm_only_path_is_unaffected():
    # No structured intel -> legacy behaviour, no suppression.
    e1 = decide_event({"detected_objects": ["person"], "description": "a person"}, "cam1", NOW, "f1")
    e2 = decide_event({"detected_objects": ["person"], "description": "a person"}, "cam1", NOW, "f2")
    assert e1 is not None and e2 is not None
