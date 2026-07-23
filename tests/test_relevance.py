"""The alert panel learns from the operator's calls: a subject they keep
dismissing sinks in the ranking, one they confirm rises, and it's reordering —
never hiding."""

from alibi.learning.relevance import RelevanceStore
from alibi.patterns.situations import rank_alerts, subject_key


def _store(tmp_path):
    return RelevanceStore(path=tmp_path / "fb.jsonl")


def test_subject_key_matches_by_person_name():
    a = {"who": "Conrad"}
    b = {"watchlist_label": "conrad"}
    assert subject_key(a) == subject_key(b) == "person:conrad"


def test_dismiss_sinks_confirm_lifts(tmp_path):
    s = _store(tmp_path)
    assert s.multiplier("person:conrad") == 1.0
    s.record("person:conrad", "dismiss")
    assert s.multiplier("person:conrad") < 1.0
    s.record("person:conrad", "dismiss")
    assert s.multiplier("person:conrad") < 0.4        # two net dismissals sink it
    # A later confirm pulls it back toward neutral (net-based).
    s.record("person:conrad", "confirm")
    assert s.multiplier("person:conrad") > 0.3


def test_dismiss_never_zeroes(tmp_path):
    s = _store(tmp_path)
    for _ in range(10):
        s.record("person:x", "dismiss")
    assert s.multiplier("person:x") >= 0.12           # floored — reordered, not hidden


def test_ranking_respects_learned_feedback(tmp_path):
    s = _store(tmp_path)
    # Two comparable stranger alerts; identical scores until feedback.
    rows = [
        {"tier": "review", "who": "Conrad", "ts": "2026-07-23T10:00:00", "severity": 3},
        {"tier": "review", "who": "Mystery", "ts": "2026-07-23T10:00:00", "severity": 3},
    ]
    before = rank_alerts([dict(r) for r in rows], limit=2)
    # Operator dismisses Conrad twice.
    s.record("person:conrad", "dismiss")
    s.record("person:conrad", "dismiss")
    adj = s.adjustments()
    after = rank_alerts([dict(r) for r in rows], limit=2, relevance=adj)
    top_subject = after[0].get("who")
    assert top_subject == "Mystery"                   # Conrad no longer leads
    conrad = next(r for r in after if r.get("who") == "Conrad")
    assert conrad["importance"] < next(r for r in before if r.get("who") == "Conrad")["importance"]


def test_summary_reports_direction(tmp_path):
    s = _store(tmp_path)
    s.record("person:conrad", "dismiss")
    rows = s.summary()
    assert rows and rows[0]["subject"] == "person:conrad"
    assert rows[0]["direction"] == "down"
