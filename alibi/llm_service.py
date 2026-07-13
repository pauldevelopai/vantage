"""
Alibi LLM Service

Optional LLM integration for generating alert text and reports.
MUST be fail-safe - all functions return None on failure.

Prefers local Ollama when available (data stays in-country),
falls back to OpenAI if configured.
"""

from typing import Optional, Tuple
import os
import requests

from alibi.schemas import Incident, IncidentPlan, Decision
from alibi.config import AlibiConfig

# Ollama settings
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "llama3.2")


def _ollama_available() -> bool:
    """Check if Ollama is running and reachable."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _call_ollama(prompt: str, system_prompt: str, max_tokens: int = 500, temperature: float = 0.3) -> Optional[str]:
    """
    Call local Ollama for text generation.

    Returns generated text or None on failure.
    """
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_TEXT_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        content = result.get("message", {}).get("content", "").strip()
        return content if content else None
    except Exception as e:
        print(f"[LLM] Ollama call failed: {e}")
        return None


def _parse_alert_response(content: str) -> Optional[Tuple[str, str]]:
    """Parse TITLE:/BODY: formatted response into (title, body) tuple."""
    lines = content.strip().split("\n")
    title = None
    body_parts = []

    in_body = False
    for line in lines:
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
        elif line.startswith("BODY:"):
            body_parts.append(line.replace("BODY:", "").strip())
            in_body = True
        elif in_body and line.strip():
            body_parts.append(line.strip())

    if title and body_parts:
        body = " ".join(body_parts)
        return (title, body)

    return None


def _build_alert_prompt(plan: IncidentPlan, incident: Incident, context=None) -> Tuple[str, str]:
    """Build system prompt and user prompt for alert generation.

    ``context`` is an optional ContextBundle of non-video facility/area context.
    It is advisory only: it informs the narrative but must never be attributed to
    the detected individual, and UNAVAILABLE sources must surface as uncertainty.
    """
    event_summary = "\n".join([
        f"  - {e.event_type} at {e.ts.strftime('%H:%M:%S')} "
        f"(conf: {e.confidence:.2f}, sev: {e.severity})"
        for e in incident.events[:5]
    ])

    if len(incident.events) > 5:
        event_summary += f"\n  ... and {len(incident.events) - 5} more events"

    context_block = ""
    if context is not None and not context.is_empty():
        rendered = context.render_for_prompt()
        if rendered:
            context_block = "\n" + rendered + "\n"

    system_prompt = "You write neutral, cautious security alerts. Never accuse or make identity claims."

    prompt = f"""You are writing an incident alert for security operators. Use NEUTRAL, CAUTIOUS language.

CRITICAL RULES:
1. NEVER use accusatory terms: suspect, criminal, perpetrator, intruder, thief
2. ALWAYS use: "possible", "appears", "may indicate", "needs review"
3. NO identity claims - say "appears to match" not "is identified as"
4. If no evidence, explicitly state "no video evidence available"
5. Facility/area context below is background only. Do NOT tie it to the detected
   individual, and never treat an UNAVAILABLE source as reassurance.

Incident: {incident.incident_id}
Time: {incident.created_ts.strftime('%Y-%m-%d %H:%M:%S')}
Events:
{event_summary}
{context_block}
Assessment:
- Severity: {plan.severity}/5
- Confidence: {plan.confidence:.2f}
- Evidence: {"Available" if plan.evidence_refs else "No clips available"}
- Recommended Action: {plan.recommended_next_step.value}
- Requires Human Review: {plan.requires_human_approval}

Generate:
1. A short alert title (under 80 chars)
2. A brief alert body (2-4 sentences) explaining what was detected and why review is needed

Format your response as:
TITLE: [your title]
BODY: [your body text]
"""
    return system_prompt, prompt


def generate_alert_text(
    plan: IncidentPlan,
    incident: Incident,
    config: AlibiConfig,
    context=None,
) -> Optional[Tuple[str, str]]:
    """
    Generate alert title and body using LLM.

    Prefers local Ollama (data stays in-country), falls back to OpenAI.
    ``context`` is an optional ContextBundle woven into the prompt as advisory
    background. Returns None if no LLM available or call fails.
    """
    system_prompt, prompt = _build_alert_prompt(plan, incident, context)

    # Try Ollama first (local, data stays in-country)
    if _ollama_available():
        content = _call_ollama(prompt, system_prompt, max_tokens=config.openai_max_tokens, temperature=config.openai_temperature)
        if content:
            result = _parse_alert_response(content)
            if result:
                return result

    # Fall back to OpenAI
    if not config.openai_api_key:
        return None

    try:
        import openai

        client = openai.OpenAI(api_key=config.openai_api_key)

        response = client.chat.completions.create(
            model=config.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=config.openai_max_tokens,
            temperature=config.openai_temperature,
        )

        content = response.choices[0].message.content
        if not content:
            return None

        return _parse_alert_response(content)

    except Exception as e:
        print(f"LLM alert generation failed: {e}")
        return None


def generate_shift_report_narrative(
    incidents: list,
    decisions: list,
    kpis: dict,
    config: AlibiConfig
) -> str:
    """
    Generate shift report narrative using LLM.

    Prefers local Ollama, falls back to OpenAI, then simple summary.
    """
    system_prompt = "You write professional security shift reports."
    prompt = f"""Summarize this security shift in 3-4 sentences.

Total Incidents: {len(incidents)}
True Positives: {kpis.get('true_positives', 0)}
False Positives: {kpis.get('false_positives', 0)}
Precision: {kpis.get('precision', 0):.1%}
Average Severity: {kpis.get('avg_severity', 0):.1f}/5

Write a professional summary for the shift supervisor. Focus on key patterns and notable incidents.
"""

    # Try Ollama first (local, data stays in-country)
    if _ollama_available():
        content = _call_ollama(prompt, system_prompt, max_tokens=300, temperature=0.4)
        if content:
            return content

    # Fall back to OpenAI
    if not config.openai_api_key:
        return _fallback_narrative(incidents, decisions, kpis)

    try:
        import openai

        client = openai.OpenAI(api_key=config.openai_api_key)

        response = client.chat.completions.create(
            model=config.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.4,
        )

        content = response.choices[0].message.content
        if content:
            return content.strip()

        return _fallback_narrative(incidents, decisions, kpis)

    except Exception as e:
        print(f"LLM report generation failed: {e}")
        return _fallback_narrative(incidents, decisions, kpis)


def _fallback_narrative(incidents: list, decisions: list, kpis: dict) -> str:
    """Simple fallback narrative without LLM"""
    total = len(incidents)
    precision = kpis.get('precision', 0)

    if total == 0:
        return "Quiet shift with no incidents detected."

    quality = "excellent" if precision > 0.9 else "good" if precision > 0.75 else "moderate"

    return (
        f"Processed {total} incident(s) during shift with {quality} detection quality "
        f"({precision:.1%} precision). "
        f"Operators reviewed {len(decisions)} case(s). "
        f"System performance within normal parameters."
    )
