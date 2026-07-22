"""
One vocabulary for "how far back?", including all time. Pinned.

Four windows had grown up independently and none of them could say
"everything". The trap in adding "all" is that its hour count is None, and a
caller that treats None as 0 shows an empty page — the exact opposite of what
the user asked for. Every None path below is deliberate.
"""

from datetime import datetime, timedelta

import pytest

from alibi import time_window as tw


NOW = datetime(2026, 7, 22, 12, 0, 0)


def test_the_four_windows_the_ui_offers():
    assert tw.WINDOWS == ("24h", "7d", "30d", "all")
    assert [o["key"] for o in tw.options()] == ["24h", "7d", "30d", "all"]
    assert all(o["label"] and o["short"] for o in tw.options())


def test_hours_for_each_window():
    assert tw.window_hours("24h") == 24
    assert tw.window_hours("7d") == 24 * 7
    assert tw.window_hours("30d") == 24 * 30
    assert tw.window_hours("all") is None          # NOT 0 — None means no cutoff


def test_all_time_applies_no_cutoff():
    assert tw.cutoff("all", now=NOW) is None
    # ...and therefore includes timestamps from any depth of history.
    assert tw.within(datetime(2019, 1, 1), "all", now=NOW) is True


def test_cutoffs_are_where_they_should_be():
    assert tw.cutoff("24h", now=NOW) == NOW - timedelta(hours=24)
    assert tw.cutoff("30d", now=NOW) == NOW - timedelta(days=30)


def test_within_filters_by_window():
    assert tw.within(NOW - timedelta(hours=2), "24h", now=NOW) is True
    assert tw.within(NOW - timedelta(hours=30), "24h", now=NOW) is False
    assert tw.within(NOW - timedelta(days=10), "30d", now=NOW) is True


def test_within_accepts_iso_strings_because_half_our_stores_use_them():
    assert tw.within((NOW - timedelta(hours=1)).isoformat(), "24h", now=NOW) is True
    assert tw.within((NOW - timedelta(days=3)).isoformat(), "24h", now=NOW) is False
    assert tw.within("not a timestamp", "24h", now=NOW) is False
    assert tw.within(None, "24h", now=NOW) is False


def test_older_spellings_still_mean_what_they_meant():
    """These were live in the codebase; silently defaulting them to 24h would
    show the wrong period without anyone noticing."""
    assert tw.normalise("week") == "7d"
    assert tw.normalise("month") == "30d"
    assert tw.normalise("everything") == "all"
    assert tw.normalise("1d") == "24h"


def test_nonsense_falls_back_rather_than_raising():
    assert tw.normalise("purple") == tw.DEFAULT
    assert tw.normalise(None) == tw.DEFAULT
    assert tw.window_hours("purple", default="7d") == 24 * 7


def test_all_time_is_described_honestly():
    assert tw.describe("all") == "All time"
    assert tw.describe("24h") == "Last 24 hours"


def test_the_or_retention_idiom_used_at_the_call_sites():
    """Endpoints write `window_hours(w) or tracker.retention_hours`. That only
    behaves if "all" is None and every real window is truthy."""
    retention = 24 * 30
    assert (tw.window_hours("all") or retention) == retention
    for w in ("24h", "7d", "30d"):
        assert (tw.window_hours(w) or retention) == tw.HOURS[w]


def test_activity_parser_gives_all_a_finite_number_of_hours():
    """That analysis buckets by hour and cannot take None."""
    from alibi.patterns.activity_patterns import parse_window
    assert parse_window("all") == 24 * 30
    assert parse_window("24h") == 24
    assert parse_window("7d") == 168
    assert parse_window("30d") == 720
    assert parse_window("1h") == 1
