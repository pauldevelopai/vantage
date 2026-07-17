"""
The paid vision model must only be called on frames the FREE local detector says
are worth it. Motion alone (wind, rain, shadows) trips the trigger constantly and
is worth $0 to narrate — at ~$0.013/call and up to one call per camera per 8s,
ungated narration runs to hundreds of dollars a day.
"""

from alibi.alibi_api import _worth_narrating


def test_person_earns_a_paid_call():
    assert _worth_narrating({"person_count": 1, "vehicle_count": 0}) is True


def test_vehicle_earns_a_paid_call():
    assert _worth_narrating({"person_count": 0, "vehicle_count": 2}) is True


def test_bare_motion_does_not_spend_money():
    # Detector found nothing — wind/shadow/rain. No paid call.
    assert _worth_narrating({"person_count": 0, "vehicle_count": 0}) is False
    assert _worth_narrating({}) is False


def test_hotlist_or_watchlist_always_earns_a_call():
    assert _worth_narrating({"hotlist_hit": True}) is True
    assert _worth_narrating({"watchlist_hit": True}) is True


def test_missing_structured_layer_falls_back_to_calling():
    # If the CV stack failed we must not go blind — degrade to the old behaviour.
    assert _worth_narrating(None) is True


# ── Baseline gates the PAID call, not just the event ───────────────────────

from datetime import datetime
from types import SimpleNamespace

from alibi.cameras import frame_analyzer as fa


def test_decide_event_uses_precomputed_newsworthiness():
    """When the endpoint already judged the frame (before the paid VLM call),
    decide_event must use that judgment — not re-run (and re-teach) the baseline."""
    intel = {"person_count": 0, "vehicle_count": 1, "plates": [], "faces": [],
             "detections": [{"class": "car", "confidence": 0.9, "bbox": [1, 1, 5, 5]}],
             "hotlist_hit": False, "watchlist_hit": False}
    now = datetime(2026, 7, 17, 12, 0, 0)

    # judged not-news -> suppressed, no baseline import needed
    ev = fa.decide_event({}, "camX", now, "f1", intel=intel,
                         newsworthiness=(False, "normal scene"))
    assert ev is None

    # judged news -> event raised, and the reason is quotable evidence
    ev = fa.decide_event({}, "camX", now, "f2", intel=intel,
                         newsworthiness=(True, "vehicle above normal"))
    assert ev is not None
    assert ev.metadata["intel"]["why_raised"] == "vehicle above normal"


def test_safety_concern_overrides_suppression():
    """If the VLM DID run and flagged a safety concern, a 'normal composition'
    judgment must not silence it."""
    intel = {"person_count": 0, "vehicle_count": 1, "plates": [], "faces": [],
             "detections": [], "hotlist_hit": False, "watchlist_hit": False}
    ev = fa.decide_event({"safety_concern": True, "description": "x"},
                         "camX", datetime(2026, 7, 17, 12, 0, 0), "f3",
                         intel=intel, newsworthiness=(False, "normal scene"))
    assert ev is not None
