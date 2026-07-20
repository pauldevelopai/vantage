"""Local (offline) vision describer — pure request/response shaping + safety."""

import base64
import json

from alibi.cameras import local_vision as lv


def test_payload_embeds_image_and_shared_prompt():
    p = lv.build_generate_payload(b"JPEGBYTES", model="llava")
    assert p["model"] == "llava"
    assert p["images"] == [base64.b64encode(b"JPEGBYTES").decode()]
    assert p["stream"] is False
    # the SAME instruction the cloud model gets (parity lever)
    assert "security camera analyst operating in South Africa" in p["prompt"]
    assert "2-3 clear, factual sentences" in p["prompt"]


def test_parse_response_extracts_text():
    raw = json.dumps({"response": "  One person in a blue shirt at the gate.  "}).encode()
    assert lv.parse_generate_response(raw) == "One person in a blue shirt at the gate."


def test_parse_response_none_on_empty_or_garbage():
    assert lv.parse_generate_response(json.dumps({"response": ""}).encode()) is None
    assert lv.parse_generate_response(b"not json") is None


def test_safety_concern_matches_cloud_keywords():
    assert lv.safety_concern("a possible weapon is visible") is True
    assert lv.safety_concern("two people chatting by a car") is False


def test_describe_returns_none_when_ollama_absent():
    # nothing listening on this port -> graceful None, never raises
    assert lv.describe(b"x", ollama_url="http://127.0.0.1:9", timeout=0.2) is None


def test_ollama_has_model_false_when_absent():
    assert lv.ollama_has_model(ollama_url="http://127.0.0.1:9", timeout=0.2) is False
