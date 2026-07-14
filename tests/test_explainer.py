"""
Tests for the "Why flagged" explainer.

Safety properties under test:
  * Reasons are GROUNDED + CITED — extracted from the incident's real signals,
    each carrying a citation to a real event / evidence / plan field.
  * Never accuses — the deterministic template and any LLM prose are free of
    forbidden accusatory language; LLM prose that sneaks it in is rejected and
    falls back to the template.
  * Fail-safe — no LLM / errors return a valid template explanation, never raise.
  * Honest empty states — no evidence is reported as "no evidence", not hidden.
"""

import sys
import types
from datetime import datetime

import pytest

from alibi import explainer
from alibi.explainer import explain_incident, extract_reasons
from alibi.config import VantageConfig
from alibi.validator import contains_forbidden_language
from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentPlan,
    IncidentStatus,
    RecommendedAction,
)


# --- fake anthropic (same shape as test_claude_llm) ------------------------- #

class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Client:
    def __init__(self, text, calls, api_key=None):
        self._text = text
        self._calls = calls
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self._calls.append(kwargs)
        return _Response(self._text)


def _install_fake_anthropic(monkeypatch, text, calls):
    module = types.ModuleType("anthropic")
    module.Anthropic = lambda api_key=None: _Client(text, calls, api_key=api_key)
    monkeypatch.setitem(sys.modules, "anthropic", module)


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    # explainer imported the name directly, so patch it on the explainer module.
    monkeypatch.setattr(explainer, "_ollama_available", lambda: False)


# --- fixtures --------------------------------------------------------------- #

def _watchlist_incident(with_evidence=True):
    ev = CameraEvent(
        event_id="evt_wl",
        camera_id="cam_3",
        ts=datetime.utcnow(),
        zone_id="z",
        event_type="watchlist_match",
        confidence=0.82,
        severity=4,
        clip_url="https://example.com/c.mp4" if with_evidence else None,
        metadata={"watchlist_match": True},
    )
    inc = Incident(
        incident_id="inc_wl",
        status=IncidentStatus.NEW,
        created_ts=datetime.utcnow(),
        updated_ts=datetime.utcnow(),
        events=[ev],
    )
    plan = IncidentPlan(
        incident_id="inc_wl",
        summary_1line="Possible watchlist match",
        severity=4,
        confidence=0.82,
        uncertainty_notes="",
        recommended_next_step=RecommendedAction.NOTIFY,
        requires_human_approval=True,
        evidence_refs=["https://example.com/c.mp4"] if with_evidence else [],
    )
    return inc, plan


# --- reason extraction (grounding + citations) ------------------------------ #

def test_reasons_are_grounded_and_cited():
    inc, plan = _watchlist_incident()
    reasons = extract_reasons(inc, plan)
    factors = {r.factor for r in reasons}

    assert "watchlist match" in factors
    assert "high severity" in factors
    assert "evidence available" in factors

    wl = next(r for r in reasons if r.factor == "watchlist match")
    # Citation points at the REAL event — not invented.
    assert wl.citation["type"] == "event"
    assert wl.citation["id"] == "evt_wl"
    assert wl.citation["confidence"] == 0.82
    assert not contains_forbidden_language(wl.detail)


def test_no_evidence_is_reported_honestly():
    inc, plan = _watchlist_incident(with_evidence=False)
    reasons = extract_reasons(inc, plan)
    factors = {r.factor for r in reasons}
    assert "no evidence" in factors
    assert "evidence available" not in factors


# --- template (no-LLM) path ------------------------------------------------- #

def test_template_when_no_llm():
    inc, plan = _watchlist_incident()
    exp = explain_incident(inc, plan, VantageConfig())  # no keys

    assert exp.method == "template"
    assert exp.grounded is True
    assert exp.reasons
    assert not contains_forbidden_language(exp.rationale)
    assert "human" in exp.rationale.lower()  # ends on human-review note
    assert exp.disclaimer


# --- Claude path ------------------------------------------------------------ #

def test_uses_claude_when_available(monkeypatch):
    calls = []
    _install_fake_anthropic(
        monkeypatch,
        "This incident was flagged because a face appears to match a watchlist "
        "entry and severity is high. It requires human review.",
        calls,
    )
    inc, plan = _watchlist_incident()
    cfg = VantageConfig(anthropic_api_key="sk-test", anthropic_model="claude-opus-4-8")

    exp = explain_incident(inc, plan, cfg)

    assert exp.method == "claude"
    assert "watchlist" in exp.rationale.lower()
    # Reasons remain the deterministic, cited set regardless of the prose source.
    assert any(r.factor == "watchlist match" for r in exp.reasons)
    assert calls and calls[0]["model"] == "claude-opus-4-8"
    assert "temperature" not in calls[0]


def test_accusatory_llm_output_is_rejected(monkeypatch):
    """If the model returns accusatory prose, discard it and use the template."""
    calls = []
    _install_fake_anthropic(monkeypatch, "The suspect is a known criminal.", calls)
    inc, plan = _watchlist_incident()
    cfg = VantageConfig(anthropic_api_key="sk-test")

    exp = explain_incident(inc, plan, cfg)

    assert exp.method == "template"  # fell back
    assert not contains_forbidden_language(exp.rationale)


def test_explainer_is_failsafe(monkeypatch):
    """A raising SDK must not propagate — template is returned."""
    module = types.ModuleType("anthropic")

    def _boom(api_key=None):
        raise RuntimeError("down")

    module.Anthropic = _boom
    monkeypatch.setitem(sys.modules, "anthropic", module)

    inc, plan = _watchlist_incident()
    exp = explain_incident(inc, plan, VantageConfig(anthropic_api_key="sk-test"))
    assert exp.method == "template"
    assert not contains_forbidden_language(exp.rationale)
