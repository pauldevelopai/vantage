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
