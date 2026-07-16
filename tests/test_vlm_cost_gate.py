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
