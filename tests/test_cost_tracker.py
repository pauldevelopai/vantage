"""Tests for usage/cost tracking: pricing maths + the JSONL record/summary."""

import json

import pytest
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


# ── Credit balance & runout ────────────────────────────────────────────────

@pytest.fixture
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "USAGE_FILE", tmp_path / "usage.jsonl")
    monkeypatch.setattr(ct, "CREDITS_FILE", tmp_path / "api_credits.json")
    return tmp_path


NOW = datetime(2026, 7, 17, 12, 0, 0)


def _spend(usd: float, days_ago: float):
    ct.record("vision", "claude-opus-4-8", 0, 0, now=NOW - timedelta(days=days_ago))
    # record() computes usd from tokens; patch the row's usd directly for exact maths
    lines = ct.USAGE_FILE.read_text().splitlines()
    row = json.loads(lines[-1])
    row["usd"] = usd
    lines[-1] = json.dumps(row)
    ct.USAGE_FILE.write_text("\n".join(lines) + "\n")


def test_credit_status_honest_nulls_when_no_balance_entered(isolated_files):
    s = ct.credit_status(now=NOW)
    assert s["balance_usd"] is None
    assert s["remaining_usd"] is None
    assert s["runout_date"] is None


def test_credit_burn_down_and_runout(isolated_files):
    # $2/day for the last 4 days (observed span 4 days)
    for d in (0.5, 1.5, 2.5, 3.5):
        _spend(2.0, d)
    ct.set_credits(100.0, set_by="admin", now=NOW - timedelta(days=2))
    s = ct.credit_status(now=NOW)
    # spend since balance entered: the 0.5d and 1.5d rows = $4
    assert s["spent_since_usd"] == 4.0
    assert s["remaining_usd"] == 96.0
    # burn: $8 over ~4 observed days ≈ $2/day (earliest row 3.5d ago -> 3.5d span)
    assert 2.0 <= s["daily_burn_usd"] <= 2.3
    assert s["days_left"] is not None and 40 <= s["days_left"] <= 50
    assert s["runout_date"] is not None
    assert s["set_by"] == "admin"


def test_credit_exhausted_reports_zero_days(isolated_files):
    _spend(60.0, 0.5)
    ct.set_credits(50.0, set_by="admin", now=NOW - timedelta(days=1))
    s = ct.credit_status(now=NOW)
    assert s["remaining_usd"] == -10.0
    assert s["days_left"] == 0.0
    assert s["runout_date"] == NOW.date().isoformat()


def test_credit_no_burn_means_no_runout_claim(isolated_files):
    ct.set_credits(50.0, set_by="admin", now=NOW)
    s = ct.credit_status(now=NOW)
    assert s["remaining_usd"] == 50.0
    assert s["days_left"] is None          # we can't honestly project with no data
    assert s["runout_date"] is None


def test_summary_includes_credits(isolated_files):
    ct.set_credits(25.0, set_by="admin", now=NOW)
    s = ct.summary(now=NOW)
    assert s["credits"]["balance_usd"] == 25.0
