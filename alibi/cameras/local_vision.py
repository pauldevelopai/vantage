"""
Local (offline) scene description on the recording PC — free, private vision.

The box can't reach a model on the PC's LAN (the recorder is outbound-only), and
the box itself is too small for a vision model. So the RECORDER describes each
motion still locally via Ollama and uploads the description with the frame; the
box uses it instead of paying for a Claude call.

Two design commitments for output PARITY with the cloud model:
  * The local model gets the EXACT same instruction as Claude — the same
    South-African/Namibian security-analyst prompt and the same 2-3 sentence,
    describe-people-and-vehicles brief. The prompt is the biggest quality lever,
    so it is shared verbatim (SCENE_PROMPT below mirrors the box prompt).
  * A capable default model (llama3.2-vision) and it's configurable, so a better
    local VLM can be swapped in without code changes.

stdlib-only (urllib) so it drops into the recorder zipapp, which carries no
numpy/opencv. Every function degrades to None/False on any failure — a missing
or slow Ollama never breaks recording or uploading.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Optional

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("VANTAGE_LOCAL_VISION_MODEL", "llama3.2-vision")

# The SAME instruction the cloud model receives (see scene_analyzer
# `_scene_system_prompt`) — kept verbatim so local output matches in shape and
# content. If the box prompt changes, update this to keep parity.
SCENE_PROMPT = (
    "You are a security camera analyst operating in South Africa and Namibia.\n\n"
    "Regional context: minibus taxis (Toyota Quantum), bakkies (pickups), "
    "townships and security estates, braais, spaza shops, burglar bars, electric "
    "fences, boom gates; wildlife in Namibia (oryx, springbok, kudu).\n\n"
    "Describe this camera frame in 2-3 clear, factual sentences.\n"
    "For PEOPLE: how many; what they wear (colours, jacket/hoodie/uniform/hi-vis); "
    "what they are doing; where in frame; anything they are CARRYING (bag, box, "
    "tools) and any ANIMAL with them (e.g. walking a dog).\n"
    "For VEHICLES: colour and body type (bakkie, SUV, sedan, minibus taxi, "
    "motorcycle); distinctive FEATURES (roof rack, towbar, canopy, bull bar, "
    "signage/livery, visible damage, spare wheel); what it is doing (parked, "
    "entering, passing); make/model ONLY if a badge is genuinely readable, "
    "otherwise omit it rather than guess.\n"
    "NEVER state or infer a person's race, ethnicity, nationality or age — only "
    "what is visibly observable, which anyone could verify from the picture.\n"
    "Note any safety concern or unusual activity. Be factual and non-judgemental — "
    "describe what you see, never accuse. If the scene is empty, say so plainly."
)

_SAFETY_WORDS = ("fight", "weapon", "attack", "theft", "break", "suspicious",
                 "danger", "emergency", "intruder", "forced")


def build_generate_payload(jpeg_bytes: bytes, model: str = DEFAULT_MODEL,
                           prompt: str = SCENE_PROMPT) -> dict:
    """The Ollama /api/generate request body for a one-shot image description.
    Pure, so it's testable without a running Ollama."""
    return {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(jpeg_bytes).decode("ascii")],
        "stream": False,
        "options": {"temperature": 0.2},
    }


def parse_generate_response(raw: bytes) -> Optional[str]:
    """Pull the description text out of an Ollama /api/generate response. Pure.
    Returns a cleaned string, or None if there's nothing usable."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    text = (data.get("response") or "").strip() if isinstance(data, dict) else ""
    return text or None


def safety_concern(description: str) -> bool:
    """Same keyword heuristic the cloud path uses, so the two agree."""
    low = (description or "").lower()
    return any(w in low for w in _SAFETY_WORDS)


def ollama_has_model(model: str = DEFAULT_MODEL, ollama_url: str = DEFAULT_OLLAMA_URL,
                     timeout: float = 2.0) -> bool:
    """True if Ollama is up locally AND the vision model is pulled. Never raises."""
    try:
        with urllib.request.urlopen(f"{ollama_url.rstrip('/')}/api/tags", timeout=timeout) as r:
            tags = json.loads(r.read())
        names = [m.get("name", "") for m in (tags.get("models") or [])]
        base = model.split(":")[0]
        return any(n == model or n.split(":")[0] == base for n in names)
    except Exception:
        return False


def describe(jpeg_bytes: bytes, model: str = DEFAULT_MODEL,
             ollama_url: str = DEFAULT_OLLAMA_URL, prompt: str = SCENE_PROMPT,
             timeout: float = 30.0) -> Optional[str]:
    """Describe a JPEG frame with the local model. Returns the description text
    or None (Ollama down/slow/absent). Never raises — the caller uploads the
    frame regardless; a missing description just means the box may narrate it."""
    if not jpeg_bytes:
        return None
    try:
        body = json.dumps(build_generate_payload(jpeg_bytes, model, prompt)).encode()
        req = urllib.request.Request(
            f"{ollama_url.rstrip('/')}/api/generate", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return parse_generate_response(r.read())
    except Exception:
        return None


def pull_model(model: str = DEFAULT_MODEL, ollama_url: str = DEFAULT_OLLAMA_URL,
               timeout: float = 3.0) -> bool:
    """Ask Ollama to pull the vision model (non-blocking best-effort — the pull
    continues server-side). Returns True if the request was accepted."""
    try:
        body = json.dumps({"name": model, "stream": False}).encode()
        req = urllib.request.Request(
            f"{ollama_url.rstrip('/')}/api/pull", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False
