"""
Tests for place-context (§9) feeding the "why flagged" explainer.

THE RULE UNDER TEST: area context is background about a PLACE. It must never
become a reason a person/vehicle was flagged, and must never be attributed to
the detected individual — that would be profiling-by-neighbourhood, which is
exactly what Vantage's safety posture exists to prevent.

Also: honest empty states. No area configured, or nothing ingested, yields no
context — never invented background, and never treated as reassurance.
"""

from datetime import datetime

import pytest

from alibi.dataengine import DataEngineStore, ingest_items
from alibi.dataengine.context import get_area_context, resolve_area_for_camera
from alibi.dataengine.sources import get_source
from alibi.explainer import explain_incident
from alibi.config import VantageConfig
from alibi.validator import contains_forbidden_language
from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentPlan,
    IncidentStatus,
    RecommendedAction,
)


@pytest.fixture
def store(tmp_path):
    s = DataEngineStore(storage_path=str(tmp_path / "de.jsonl"))
    ingest_items(
        get_source("places.area_crime_stats"),
        [{"area": "Sandton", "period": "2026Q1", "crime_category": "vehicle theft",
          "count": 42, "source_url": "https://example.gov/stats"}],
        s,
    )
    return s


def _incident_and_plan():
    ev = CameraEvent(
        event_id="evt_1", camera_id="cam_1", ts=datetime.utcnow(), zone_id="z",
        event_type="watchlist_match", confidence=0.82, severity=4,
        clip_url="https://example.com/c.mp4", metadata={"watchlist_match": True},
    )
    inc = Incident(
        incident_id="inc_1", status=IncidentStatus.NEW,
        created_ts=datetime.utcnow(), updated_ts=datetime.utcnow(), events=[ev],
    )
    plan = IncidentPlan(
        incident_id="inc_1", summary_1line="Possible watchlist match", severity=4,
        confidence=0.82, uncertainty_notes="",
        recommended_next_step=RecommendedAction.NOTIFY,
        requires_human_approval=True,
        evidence_refs=["https://example.com/c.mp4"],
    )
    return inc, plan


class TestAreaContextLookup:

    def test_finds_context_for_known_area(self, store):
        ctx = get_area_context("Sandton", store=store)
        assert not ctx.is_empty()
        assert "42" in ctx.items[0].detail
        # Cited back to the ingested record + its lawful basis
        assert ctx.items[0].citation["source_id"] == "places.area_crime_stats"
        assert ctx.items[0].citation["lawful_basis"]
        assert ctx.items[0].citation["source_url"] == "https://example.gov/stats"

    def test_case_insensitive(self, store):
        assert not get_area_context("sandton", store=store).is_empty()

    def test_unknown_area_is_honestly_empty(self, store):
        ctx = get_area_context("Nowhereville", store=store)
        assert ctx.is_empty()
        assert ctx.items == []          # never invented
        assert ctx.render_for_prompt() == ""

    def test_no_area_configured_is_empty(self, store):
        assert get_area_context("", store=store).is_empty()

    def test_context_carries_the_rule(self, store):
        ctx = get_area_context("Sandton", store=store)
        rendered = ctx.render_for_prompt()
        assert "not evidence about the detected person" in rendered.lower()

    def test_camera_without_area_resolves_empty(self):
        """No guessing — a camera with no area set yields no area."""
        assert resolve_area_for_camera("definitely-not-a-camera") == ""


class TestContextNeverBecomesAReason:
    """The load-bearing safety test."""

    def test_area_context_is_separate_from_reasons(self, store):
        inc, plan = _incident_and_plan()
        ctx = get_area_context("Sandton", store=store)

        exp = explain_incident(inc, plan, VantageConfig(), context=ctx)

        # Context is present...
        assert exp.area_context is not None
        assert exp.area_context["area"] == "Sandton"
        # ...but it is NOT one of the reasons the incident was flagged.
        reason_factors = {r.factor for r in exp.reasons}
        assert "crime_stats" not in reason_factors
        assert not any("statistic" in r.detail.lower() for r in exp.reasons)
        assert not any("Sandton" in r.detail for r in exp.reasons)

    def test_template_rationale_does_not_cite_area_stats_as_a_reason(self, store):
        """The no-LLM rationale is built from reasons only — area stats can't leak in."""
        inc, plan = _incident_and_plan()
        ctx = get_area_context("Sandton", store=store)

        exp = explain_incident(inc, plan, VantageConfig(), context=ctx)

        assert exp.method == "template"
        assert "42" not in exp.rationale        # the crime count is not a reason
        assert "Sandton" not in exp.rationale
        assert not contains_forbidden_language(exp.rationale)

    def test_explanation_works_without_context(self):
        """No context -> explanation still valid, area_context is None (honest)."""
        inc, plan = _incident_and_plan()
        exp = explain_incident(inc, plan, VantageConfig(), context=None)
        assert exp.area_context is None
        assert exp.reasons  # reasons are unaffected

    def test_empty_context_is_not_attached(self, store):
        """An empty context must not be attached as if it were background."""
        inc, plan = _incident_and_plan()
        ctx = get_area_context("Nowhereville", store=store)
        exp = explain_incident(inc, plan, VantageConfig(), context=ctx)
        assert exp.area_context is None  # absent, not an empty shell
