"""
The Security Advisor's judgement IS the feature, so it's pinned here. Rules:
every recommendation must come from observed state, a healthy system must produce
NOTHING (an advisor that always talks is noise), and it advises on the system —
never on people.
"""

from alibi.advisor import build_recommendations, summarise

HEALTHY = {
    "recorders_total": 1, "recorders_online": 1,
    "cameras_total": 2, "cameras_unassigned": [],
    "sites": [{"name": "My House", "camera_ids": ["a", "b"],
               "has_context": True, "has_hours": True, "area": "Parkview"}],
    "quiet_cameras": [], "window_hours": 24,
    "hotlist_count": 3, "watchlist_count": 1, "incident_count": 4,
    "intel_sources": 1, "vision_backend": "claude",
}


def _keys(state):
    return {r.key for r in build_recommendations(state)}


def test_healthy_system_gets_no_noise():
    assert build_recommendations(HEALTHY) == []
    assert "looks sound" in summarise([])


def test_no_recorder_is_critical_and_ranked_first():
    recs = build_recommendations({**HEALTHY, "recorders_total": 0, "recorders_online": 0})
    assert recs[0].key == "no_recorder"
    assert recs[0].priority == "critical"


def test_offline_recorder_is_critical():
    recs = build_recommendations({**HEALTHY, "recorders_online": 0})
    assert any(r.key == "recorder_offline" and r.priority == "critical" for r in recs)


def test_fallback_vision_is_flagged():
    recs = build_recommendations({**HEALTHY, "vision_backend": "basic_cv"})
    r = next(r for r in recs if r.key == "weak_vision")
    assert r.priority == "high"
    assert "brightness" in r.detail          # says WHY it's bad, in plain terms


def test_unassigned_cameras_are_flagged_with_evidence():
    recs = build_recommendations({**HEALTHY, "cameras_unassigned": ["cam-91", "cam-92"]})
    r = next(r for r in recs if r.key == "cameras_unassigned")
    assert "cam-91" in r.evidence            # cites the actual cameras
    assert "2 cameras" in r.title


def test_site_gaps_are_each_called_out():
    state = {**HEALTHY, "sites": [{"name": "Office", "camera_ids": ["a"],
                                   "has_context": False, "has_hours": False, "area": ""}]}
    k = _keys(state)
    assert "site_no_hours:Office" in k
    assert "site_no_context:Office" in k
    assert "site_no_area:Office" in k


def test_site_with_no_cameras_short_circuits_to_one_finding():
    state = {**HEALTHY, "sites": [{"name": "Shed", "camera_ids": [],
                                   "has_context": False, "has_hours": False, "area": ""}]}
    k = _keys(state)
    assert "site_no_cameras:Shed" in k
    assert "site_no_hours:Shed" not in k     # don't pile on — fix the real problem first


def test_quiet_cameras_only_flagged_when_others_saw_something():
    # A quiet window everywhere is not a blind spot — stay quiet.
    assert "quiet_cameras" not in _keys({**HEALTHY, "quiet_cameras": ["cam-92"], "incident_count": 0})
    # But quiet WHILE others were active is worth checking.
    assert "quiet_cameras" in _keys({**HEALTHY, "quiet_cameras": ["cam-92"], "incident_count": 5})


def test_empty_lists_are_suggested():
    k = _keys({**HEALTHY, "hotlist_count": 0, "watchlist_count": 0, "intel_sources": 0})
    assert {"empty_hotlist", "empty_watchlist", "no_intel"} <= k


def test_priority_ordering_puts_critical_first():
    recs = build_recommendations({**HEALTHY, "recorders_online": 0, "hotlist_count": 0,
                                  "watchlist_count": 0})
    ranks = ["critical", "high", "medium", "low"]
    got = [ranks.index(r.priority) for r in recs]
    assert got == sorted(got)


def test_every_recommendation_carries_evidence_and_an_action():
    recs = build_recommendations({"recorders_total": 0, "cameras_total": 0,
                                  "hotlist_count": 0, "watchlist_count": 0, "intel_sources": 0,
                                  "vision_backend": "basic_cv"})
    assert recs
    for r in recs:
        assert r.evidence, f"{r.key} has no evidence"
        assert r.action, f"{r.key} has no action"
        assert r.priority in ("critical", "high", "medium", "low")


def test_unknown_state_stays_quiet_rather_than_guessing():
    # Nothing known -> we must not invent advice.
    assert build_recommendations({}) == []


def test_summary_leads_with_the_worst():
    assert "attention now" in summarise(build_recommendations({**HEALTHY, "recorders_online": 0}))
