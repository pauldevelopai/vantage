"""
Tests for the OpenAI -> Claude (Anthropic) shift.

Verifies that:
  * Claude is the preferred CLOUD tier for both text (alerts/reports) and vision
    (scene analysis), sitting after local Ollama and before OpenAI.
  * The Anthropic call is well-formed: it uses the configured model, sends the
    system prompt + native image block, and never sends `temperature` (the
    current Opus models reject sampling params with a 400).
  * Everything stays fail-safe: no key / SDK errors return None or fall through,
    never raising.

A fake `anthropic` module is injected into ``sys.modules`` so no network call
and no real SDK install is needed.
"""

import sys
import types
from datetime import datetime

import numpy as np
import pytest

from alibi import llm_service
from alibi.config import VantageConfig
from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentPlan,
    IncidentStatus,
    RecommendedAction,
)
from alibi.vision.scene_analyzer import SceneAnalyzer


# --------------------------------------------------------------------------- #
# Fake anthropic SDK
# --------------------------------------------------------------------------- #

class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, text, calls):
        self._text = text
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return _Response(self._text)


class _Client:
    def __init__(self, text, calls, api_key=None):
        self.api_key = api_key
        self.messages = _Messages(text, calls)


def _install_fake_anthropic(monkeypatch, text, calls, raises=False):
    """Insert a fake `anthropic` module. Returns nothing; `calls` collects the
    kwargs every `messages.create` was invoked with."""
    module = types.ModuleType("anthropic")

    def _factory(api_key=None):
        if raises:
            raise RuntimeError("boom")
        return _Client(text, calls, api_key=api_key)

    module.Anthropic = _factory
    monkeypatch.setitem(sys.modules, "anthropic", module)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    """Force the local tier off so tests exercise the cloud path deterministically."""
    monkeypatch.setattr(llm_service, "_ollama_available", lambda: False)


def _incident():
    ev = CameraEvent(
        event_id="evt_1",
        camera_id="cam_1",
        ts=datetime.utcnow(),
        zone_id="zone_a",
        event_type="person_detected",
        confidence=0.82,
        severity=3,
        clip_url="https://example.com/clip1.mp4",
        snapshot_url="https://example.com/snap1.jpg",
        metadata={},
    )
    return Incident(
        incident_id="inc_1",
        status=IncidentStatus.NEW,
        created_ts=datetime.utcnow(),
        updated_ts=datetime.utcnow(),
        events=[ev],
    )


def _plan():
    return IncidentPlan(
        incident_id="inc_1",
        summary_1line="Possible person detected in zone",
        severity=3,
        confidence=0.82,
        uncertainty_notes="None",
        recommended_next_step=RecommendedAction.NOTIFY,
        requires_human_approval=True,
        evidence_refs=["https://example.com/clip1.mp4"],
    )


# --------------------------------------------------------------------------- #
# Text: alerts + reports
# --------------------------------------------------------------------------- #

def test_alert_text_uses_claude(monkeypatch):
    calls = []
    _install_fake_anthropic(
        monkeypatch, "TITLE: Possible person\nBODY: A person appears; needs review.", calls
    )
    cfg = VantageConfig(anthropic_api_key="sk-test", anthropic_model="claude-opus-4-8")

    result = llm_service.generate_alert_text(_plan(), _incident(), cfg)

    assert result == ("Possible person", "A person appears; needs review.")
    assert len(calls) == 1
    # Correct model, system prompt present, and NO sampling params (would 400 on Opus).
    assert calls[0]["model"] == "claude-opus-4-8"
    assert "system" in calls[0] and calls[0]["system"]
    assert "temperature" not in calls[0]
    assert "top_p" not in calls[0]


def test_shift_report_uses_claude(monkeypatch):
    calls = []
    _install_fake_anthropic(monkeypatch, "Quiet shift, two incidents, all reviewed.", calls)
    cfg = VantageConfig(anthropic_api_key="sk-test")

    narrative = llm_service.generate_shift_report_narrative(
        incidents=[_incident()], decisions=[], kpis={"precision": 0.9}, config=cfg
    )

    assert narrative == "Quiet shift, two incidents, all reviewed."
    assert calls and calls[0]["model"] == "claude-opus-4-8"


def test_claude_preferred_over_openai(monkeypatch):
    """When both cloud keys are set, Claude wins and OpenAI is never touched."""
    calls = []
    _install_fake_anthropic(monkeypatch, "TITLE: T\nBODY: B.", calls)

    def _fail_openai(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("OpenAI must not be called when Claude succeeds")

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_fail_openai))
    cfg = VantageConfig(anthropic_api_key="sk-test", openai_api_key="sk-openai")

    assert llm_service.generate_alert_text(_plan(), _incident(), cfg) == ("T", "B.")


def test_no_anthropic_key_no_claude_call(monkeypatch):
    calls = []
    _install_fake_anthropic(monkeypatch, "should not be used", calls)
    cfg = VantageConfig()  # no keys at all

    assert llm_service.generate_alert_text(_plan(), _incident(), cfg) is None
    assert calls == []  # Claude tier skipped without a key


def test_claude_failure_is_failsafe(monkeypatch):
    """SDK/construction errors must return None, never raise."""
    _install_fake_anthropic(monkeypatch, "", [], raises=True)
    cfg = VantageConfig(anthropic_api_key="sk-test")

    assert llm_service.generate_alert_text(_plan(), _incident(), cfg) is None


# --------------------------------------------------------------------------- #
# Vision: scene analysis
# --------------------------------------------------------------------------- #

def test_scene_analyzer_claude_mode(monkeypatch):
    calls = []
    _install_fake_anthropic(
        monkeypatch, "A person stands near a parked bakkie in a residential yard.", calls
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_VISION_MODEL", "claude-opus-4-8")

    analyzer = SceneAnalyzer(mode="claude")
    assert analyzer.claude_available is True

    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    result = analyzer.analyze_frame(frame, prompt="describe_scene")

    assert result["method"] == "claude_vision"
    assert "bakkie" in result["description"]
    assert "person" in result["detected_objects"]

    # The request carried a native base64 image block and the configured model,
    # with no sampling params.
    assert calls[0]["model"] == "claude-opus-4-8"
    content = calls[0]["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in content)
    assert "temperature" not in calls[0]


def test_scene_analyzer_auto_prefers_claude_over_openai(monkeypatch):
    """In auto mode with no Ollama, Claude is chosen ahead of OpenAI/Google."""
    calls = []
    _install_fake_anthropic(monkeypatch, "Empty driveway, no people visible.", calls)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    analyzer = SceneAnalyzer(mode="auto")
    analyzer.ollama_available = False  # ensure local tier off regardless of host
    # Pretend OpenAI is also configured; Claude must still win.
    analyzer.openai_available = True

    result = analyzer.analyze_frame(np.zeros((16, 16, 3), dtype=np.uint8))
    assert result["method"] == "claude_vision"
