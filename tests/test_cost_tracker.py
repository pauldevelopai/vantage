"""Tests for usage/cost tracking: pricing maths + the JSONL record/summary."""

from datetime import datetime, timedelta

import alibi.cost_tracker as ct


def test_cost_usd_opus():
    # 1M in @ $5, 1M out @ $25
    assert ct.cost_usd("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0
    assert ct.cost_usd("claude-opus-4-8", 0, 0) == 0.0


def test_cost_usd_haiku_cheaper():
    assert ct.cost_usd("claude-haiku-4-5", 1_000_000, 0) == 1.0


def test_unknown_model_priced_as_opus_tier():
    assert ct.cost_usd("mystery", 1_000_000, 0) == 5.0   # don't undercount


def test_record_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "USAGE_FILE", tmp_path / "usage.jsonl")
    now = datetime(2026, 7, 16, 12, 0, 0)
    ct.record("vision", "claude-opus-4-8", 1000, 500, now=now)
    ct.record("llm_text", "claude-opus-4-8", 2000, 1000, now=now)
    ct.record("vision", "claude-opus-4-8", 1000, 500, now=now - timedelta(days=1))

    s = ct.summary(window_days=30, now=now)
    assert s["currency"] == "USD"
    assert s["by_service"]["vision"]["calls"] == 2
    assert s["by_service"]["llm_text"]["calls"] == 1
    assert s["total_usd"] > 0
    # per-day breakdown spans the two days
    assert len(s["by_day"]) == 2


def test_summary_respects_window(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "USAGE_FILE", tmp_path / "usage.jsonl")
    now = datetime(2026, 7, 16, 12, 0, 0)
    ct.record("vision", "claude-opus-4-8", 1000, 500, now=now - timedelta(days=40))
    s = ct.summary(window_days=30, now=now)
    assert s["total_usd"] == 0.0            # the only record is outside the window


def test_summary_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "USAGE_FILE", tmp_path / "nope.jsonl")
    s = ct.summary(now=datetime(2026, 7, 16))
    assert s["total_usd"] == 0.0 and s["by_service"] == {}


def test_record_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "USAGE_FILE", tmp_path / "usage.jsonl")
    ct.record("x", "claude-opus-4-8", None, None)   # None tokens must not blow up
