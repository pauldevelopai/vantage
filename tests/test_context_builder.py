"""
Tests for external-context fusion (alibi.context) and its caution-only wiring
into the incident advisor.

Safety invariants under test:
  - context is CAUTION-ONLY: it may add risk flags / force review, but never
    lowers severity, changes the recommended action, or downgrades review.
  - a provider that raises becomes one UNAVAILABLE item (never crashes).
  - accusatory language in a context item is neutralised before use.
  - an UNAVAILABLE source is surfaced, never rendered as "all clear".
"""

from datetime import datetime

import pytest

from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentStatus,
    RecommendedAction,
)
from alibi.config import AlibiConfig
from alibi.context import Availability, ContextBundle, ContextItem, ContextProvider, build_context
from alibi.context.builder import _neutralize
from alibi.alibi_engine import build_incident_plan, compile_alert


def _incident(severity=2, confidence=0.9, event_type="person_detected"):
    ev = CameraEvent(
        event_id="evt_1",
        camera_id="cam_north",
        ts=datetime(2026, 1, 18, 2, 0, 0),
        zone_id="zone_dock",
        event_type=event_type,
        confidence=confidence,
        severity=severity,
        clip_url="https://example.com/clip.mp4",
    )
    return Incident(
        incident_id="inc_1",
        status=IncidentStatus.NEW,
        created_ts=ev.ts,
        updated_ts=ev.ts,
        events=[ev],
    )


class _FakeProvider(ContextProvider):
    name = "fake"

    def __init__(self, items):
        self._items = items

    def fetch(self, incident, config=None):
        return self._items


class _BoomProvider(ContextProvider):
    name = "boom"

    def fetch(self, incident, config=None):
        raise RuntimeError("source down")


# --- builder is fail-safe ---------------------------------------------------

def test_provider_exception_becomes_unavailable_item():
    bundle = build_context(_incident(), providers=[_BoomProvider()])
    assert len(bundle.items) == 1
    assert bundle.items[0].availability == Availability.UNAVAILABLE
    assert bundle.items[0].provider == "boom"


def test_default_providers_run_without_crashing():
    # No stores populated in a fresh test env -> honest ABSENT/UNAVAILABLE, no crash.
    bundle = build_context(_incident())
    assert isinstance(bundle, ContextBundle)
    assert len(bundle.items) == 3  # baseline, intelligence, known_persons


# --- neutrality guard -------------------------------------------------------

def test_neutralize_strips_accusatory_language():
    assert "suspect" not in _neutralize("the suspect is here").lower()


def test_builder_neutralises_item_summaries():
    item = ContextItem(
        provider="fake", label="Fake", availability=Availability.PRESENT,
        summary="a suspect was seen", source="test",
    )
    bundle = build_context(_incident(), providers=[_FakeProvider([item])])
    assert "suspect" not in bundle.items[0].summary.lower()


# --- caution-only application ----------------------------------------------

def test_context_can_force_human_review_but_not_change_action():
    item = ContextItem(
        provider="fake", label="Fake", availability=Availability.PRESENT,
        summary="activity appears unusual", source="test",
        caution_signals=["activity_anomaly_vs_baseline"], elevate_review=True,
    )
    bundle = ContextBundle(items=[item])

    base = build_incident_plan(_incident(severity=2, confidence=0.9))
    fused = build_incident_plan(_incident(severity=2, confidence=0.9), context=bundle)

    # review forced on, flag added
    assert fused.requires_human_approval is True
    assert "activity_anomaly_vs_baseline" in fused.action_risk_flags
    # action + severity unchanged (caution-only never re-routes or de/escalates action)
    assert fused.recommended_next_step == base.recommended_next_step
    assert fused.severity == base.severity


def test_context_never_lowers_review_requirement():
    # High-severity incident already requires review; an empty/benign bundle
    # must not turn that off.
    benign = ContextBundle(items=[ContextItem(
        provider="fake", label="Fake", availability=Availability.PRESENT,
        summary="within normal range", source="test",
    )])
    plan = build_incident_plan(_incident(severity=5, confidence=0.9), context=benign)
    assert plan.requires_human_approval is True


def test_low_confidence_still_monitors_with_context():
    # Rule 2 (low confidence -> monitor) must survive context fusion.
    item = ContextItem(
        provider="fake", label="Fake", availability=Availability.PRESENT,
        summary="unusual", source="test",
        caution_signals=["x"], elevate_review=True,
    )
    plan = build_incident_plan(
        _incident(severity=2, confidence=0.4),
        context=ContextBundle(items=[item]),
    )
    assert plan.recommended_next_step == RecommendedAction.MONITOR


# --- surfacing / audit ------------------------------------------------------

def test_unavailable_source_surfaced_in_disclaimer():
    bundle = ContextBundle(items=[ContextItem(
        provider="sched", label="Shift schedule", availability=Availability.UNAVAILABLE,
        source="not configured",
    )])
    inc = _incident(severity=2, confidence=0.9)
    plan = build_incident_plan(inc, context=bundle)
    alert = compile_alert(plan, inc, config=AlibiConfig(), context=bundle)
    assert "could not be verified" in alert.disclaimer.lower()
    assert "Shift schedule" in alert.disclaimer


def test_context_recorded_on_incident_for_audit():
    bundle = ContextBundle(items=[ContextItem(
        provider="fake", label="Fake", availability=Availability.PRESENT,
        summary="within normal range", source="test",
    )])
    inc = _incident()
    plan = build_incident_plan(inc, context=bundle)
    compile_alert(plan, inc, config=AlibiConfig(), context=bundle)
    assert "external_context" in inc.metadata
    assert inc.metadata["external_context"]["items"][0]["label"] == "Fake"


def test_render_for_prompt_flags_unavailable():
    bundle = ContextBundle(items=[ContextItem(
        provider="w", label="Weather", availability=Availability.UNAVAILABLE, source="x",
    )])
    rendered = bundle.render_for_prompt()
    assert "UNAVAILABLE" in rendered


# --- backward compatibility -------------------------------------------------

def test_plan_and_alert_unchanged_without_context():
    inc = _incident(severity=3, confidence=0.9)
    plan = build_incident_plan(inc)  # no context arg
    alert = compile_alert(plan, inc, config=AlibiConfig())  # no context arg
    assert "external_context" not in inc.metadata
    assert alert.incident_id == "inc_1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
