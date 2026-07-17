"""
Tests for phase-4 frame AI: the pure decision (vision result -> optional event),
the per-camera throttle, and evidence-frame storage. The cv2 decode + vision call
are wiring around these and aren't exercised here.
"""

from datetime import datetime

from alibi.cameras.frame_analyzer import (
    decide_event,
    should_analyze,
    store_frame,
    get_frame,
    ANALYZE_MIN_GAP_SECONDS,
)
from alibi.validator import contains_forbidden_language

NOW = datetime(2026, 7, 16, 3, 0, 0)


def _r(objects=None, desc="", confidence=0.8, safety=False):
    return {"detected_objects": objects or [], "description": desc,
            "confidence": confidence, "safety_concern": safety}


# --- decide_event ---------------------------------------------------------- #

def test_person_makes_person_event():
    e = decide_event(_r(objects=["person"], desc="A person at the gate"), "cam1", NOW, "f1")
    assert e.event_type == "person_detected"
    assert e.severity == 3
    assert e.camera_id == "cam1"
    assert e.snapshot_url == "/api/cameras/frames/f1.jpg"
    assert e.metadata["source"] == "frame_ai"


def test_vehicle_makes_vehicle_event():
    e = decide_event(_r(objects=["car"], desc="A car in the driveway"), "cam1", NOW, "f2")
    assert e.event_type == "vehicle_detected" and e.severity == 2


def test_nothing_notable_returns_none():
    assert decide_event(_r(desc="An empty garden, trees swaying"), "cam1", NOW, "f3") is None


def test_safety_concern_bumps_severity_but_caps():
    e = decide_event(_r(objects=["person"], safety=True), "cam1", NOW, "f4")
    assert e.severity == 4                      # 3 + 1, capped below the max (5)
    e2 = decide_event(_r(objects=["person", "person"], desc="fighting", safety=True,
                         confidence=0.9), "cam1", NOW, "f5")
    assert e2.severity <= 4


def test_confidence_clamped():
    e = decide_event(_r(objects=["person"], confidence=5.0), "cam1", NOW, "f6")
    assert 0.0 <= e.confidence <= 1.0
    e2 = decide_event(_r(objects=["person"], confidence="bad"), "cam1", NOW, "f7")
    assert e2.confidence == 0.7                 # fallback


def test_event_types_are_never_accusatory():
    for objs in (["person"], ["car"], []):
        e = decide_event(_r(objects=objs, desc="something", safety=True), "cam1", NOW, "fz")
        if e:
            assert not contains_forbidden_language(e.event_type)
            assert e.event_type in ("person_detected", "vehicle_detected", "activity_detected")


# --- structured CV intel drives the event --------------------------------- #

def test_structured_person_detection_makes_event_even_if_vlm_blind():
    # VLM saw nothing, but the detector found a person -> real event.
    intel = {"person_count": 1, "vehicle_count": 0}
    e = decide_event(_r(desc="quiet scene"), "cam1", NOW, "f8", intel=intel)
    assert e is not None and e.event_type == "person_detected"
    assert e.metadata["intel"]["person_count"] == 1


def test_structured_vehicle_detection_makes_vehicle_event():
    intel = {"person_count": 0, "vehicle_count": 2}
    e = decide_event(_r(desc="driveway"), "cam1", NOW, "f9", intel=intel)
    assert e.event_type == "vehicle_detected"
    assert e.metadata["intel"]["vehicle_count"] == 2


def test_hotlist_plate_raises_event_and_maxes_review_severity():
    # Nothing else notable, but a hotlist plate is the strongest "worth a look".
    intel = {"hotlist_hit": True, "hotlist_reason": "stolen",
             "plates": [{"text": "CA123456", "display": "CA 123 456"}]}
    e = decide_event(_r(desc="a car passes"), "cam1", NOW, "f10", intel=intel)
    assert e is not None
    assert e.severity == 4                        # bumped to the review ceiling
    assert e.metadata["intel"]["hotlist_hit"] is True
    assert e.metadata["intel"]["plates"][0]["display"] == "CA 123 456"


def test_watchlist_face_raises_event():
    intel = {"watchlist_hit": True, "watchlist_label": "Person of interest"}
    e = decide_event(_r(desc="someone at the gate"), "cam1", NOW, "f11", intel=intel)
    assert e is not None and e.severity == 4
    assert e.metadata["intel"]["watchlist_label"] == "Person of interest"


def test_intel_absent_preserves_legacy_behaviour():
    # No intel -> identical to before (VLM-only decision).
    assert decide_event(_r(desc="empty garden"), "cam1", NOW, "f12") is None
    e = decide_event(_r(objects=["person"]), "cam1", NOW, "f13")
    assert e.event_type == "person_detected" and "intel" not in e.metadata


def test_hotlist_and_watchlist_labels_are_not_accusatory():
    intel = {"hotlist_hit": True, "watchlist_hit": True,
             "watchlist_label": "match", "hotlist_reason": "flagged"}
    e = decide_event(_r(objects=["person", "car"]), "cam1", NOW, "f14", intel=intel)
    assert not contains_forbidden_language(e.event_type)
    assert e.event_type in ("person_detected", "vehicle_detected", "activity_detected")


# --- throttle -------------------------------------------------------------- #

def test_throttle_one_per_gap():
    cam = "throttle-cam-a"
    assert should_analyze(cam, now=1000.0) is True
    assert should_analyze(cam, now=1000.0 + 1) is False        # too soon
    assert should_analyze(cam, now=1000.0 + ANALYZE_MIN_GAP_SECONDS + 1) is True


def test_throttle_is_per_camera():
    assert should_analyze("throttle-cam-b", now=5000.0) is True
    assert should_analyze("throttle-cam-c", now=5000.0) is True  # different camera, allowed


# --- evidence storage ------------------------------------------------------ #

def test_store_and_get_frame(tmp_path, monkeypatch):
    import alibi.cameras.frame_analyzer as fa
    monkeypatch.setattr(fa, "FRAMES_DIR", tmp_path / "frames")
    fid = store_frame(b"\xff\xd8\xff\xe0jpegbytes")
    assert get_frame(fid) == b"\xff\xd8\xff\xe0jpegbytes"
    assert get_frame("nope") is None
    assert get_frame("../escape") is None       # sanitized


# --- the detector is the answer; prose is not evidence ---------------------- #

def test_a_denial_is_not_a_sighting():
    """Claude's real words on Paul's empty garden. Substring-matching them read
    "No people are visible" as a person sighting and stamped person_detected on an
    empty scene, every frame."""
    denial = _r(desc="No people are visible in this nighttime frame. The scene shows a "
                     "residential front garden with potted plants and a palisade fence.")
    assert decide_event(denial, "cam1", NOW, "fx", intel={"person_count": 0, "vehicle_count": 0}) is None


def test_detector_counts_decide_the_event_type_not_the_prose():
    # Prose mentions people (in a denial) but the detector saw only a vehicle.
    e = decide_event(_r(desc="No people are visible; a car is parked."), "cam-a", NOW, "f1",
                     intel={"person_count": 0, "vehicle_count": 1})
    assert e is not None and e.event_type == "vehicle_detected"


def test_detector_beats_prose_that_missed_a_person():
    # Prose says nothing; the detector is confident. Trust the detector.
    e = decide_event(_r(desc="A quiet driveway."), "cam-b", NOW, "f2",
                     intel={"person_count": 2, "vehicle_count": 0})
    assert e is not None and e.event_type == "person_detected"


def test_prose_fallback_still_works_without_a_detector():
    # No intel at all -> the text match is all we have, so it must still fire.
    e = decide_event(_r(objects=["person"], desc="a person at the gate"), "cam-c", NOW, "f3")
    assert e is not None and e.event_type == "person_detected"
