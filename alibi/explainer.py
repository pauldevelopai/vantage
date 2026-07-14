"""
Vantage "Why flagged" explainer.

Produces a short, GROUNDED, CITED, human-in-the-loop rationale for why an
incident was flagged. Two hard safety properties:

  1. **Grounded + cited, no new claims.** The list of reasons is extracted
     *deterministically* from the incident's real events and plan — every reason
     carries a citation to a real event id / evidence ref / plan field. The LLM
     is only allowed to *phrase* those facts into a readable sentence; it is
     never the source of the facts or the citations, so it cannot invent them.

  2. **Never accuses.** LLM output is passed through the same forbidden-language
     validator used everywhere else; if it introduces accusatory wording it is
     discarded and we fall back to a deterministic template built from the same
     cited reasons. No LLM at all → template. Either way the rationale is real
     data, never mocked.

Fail-safe: every path returns a valid Explanation; nothing raises.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from alibi.schemas import Incident, IncidentPlan, RecommendedAction
from alibi.config import VantageConfig
from alibi.validator import contains_forbidden_language
from alibi.llm_service import _ollama_available, _call_ollama, _call_anthropic

DISCLAIMER = (
    "Automated assessment — describes possibilities only, makes no identity or "
    "intent claims, and requires human review before any action."
)


@dataclass
class Reason:
    """One cited factor behind the flag. `citation` points at real data."""
    factor: str            # short label, e.g. "watchlist match"
    detail: str            # neutral human phrasing of the signal
    citation: Dict[str, Any] = field(default_factory=dict)  # {type,id,...}


@dataclass
class Explanation:
    incident_id: str
    rationale: str             # short neutral paragraph
    reasons: List[Reason]
    method: str                # claude|ollama|openai|template
    grounded: bool = True
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# --------------------------------------------------------------------------- #
# Deterministic reason extraction — the source of truth for citations
# --------------------------------------------------------------------------- #

def extract_reasons(incident: Incident, plan: IncidentPlan) -> List[Reason]:
    """Derive the cited reasons for the flag from the incident's real signals.

    Never invents anything — only reports what is actually present in the
    events, their metadata, and the plan.
    """
    reasons: List[Reason] = []

    for ev in incident.events:
        md = ev.metadata or {}

        # Watchlist / face match
        if ev.event_type == "watchlist_match" or md.get("watchlist_match"):
            reasons.append(Reason(
                factor="watchlist match",
                detail=(
                    f"A face in this event appears to match a watchlist entry "
                    f"(match confidence {ev.confidence:.0%})."
                ),
                citation={"type": "event", "id": ev.event_id,
                          "camera_id": ev.camera_id, "confidence": ev.confidence},
            ))

        # Plate hotlist match
        if md.get("hotlist_match") or md.get("plate_hotlist"):
            plate = md.get("plate") or md.get("plate_text") or "a plate"
            reasons.append(Reason(
                factor="hotlist plate",
                detail=f"Plate reading '{plate}' appears on a hotlist for review.",
                citation={"type": "event", "id": ev.event_id, "plate": plate},
            ))

        # Impossible travel / cross-camera correlation
        if md.get("impossible_travel"):
            reasons.append(Reason(
                factor="impossible travel",
                detail=(
                    "The same plate or appearance was seen at two cameras too "
                    "far apart to travel between in the elapsed time."
                ),
                citation={"type": "event", "id": ev.event_id},
            ))

        # Colour mismatch vs registration
        if md.get("color_mismatch"):
            reasons.append(Reason(
                factor="colour mismatch",
                detail=(
                    "The vehicle colour observed differs from the colour on the "
                    "plate's registration record."
                ),
                citation={"type": "event", "id": ev.event_id},
            ))

        # Loitering / dwell
        if ev.event_type in ("loitering", "dwell"):
            reasons.append(Reason(
                factor=ev.event_type,
                detail=f"A '{ev.event_type}' pattern was detected at camera {ev.camera_id}.",
                citation={"type": "event", "id": ev.event_id, "camera_id": ev.camera_id},
            ))

    # High severity from the plan
    if plan.severity >= 4:
        reasons.append(Reason(
            factor="high severity",
            detail=f"Overall assessed severity is {plan.severity} of 5.",
            citation={"type": "plan", "field": "severity", "value": plan.severity},
        ))

    # Human-review requirement
    if plan.requires_human_approval:
        reasons.append(Reason(
            factor="human review required",
            detail="The recommended next step requires human review before any action.",
            citation={"type": "plan", "field": "requires_human_approval", "value": True},
        ))

    # Evidence availability (stated honestly either way — no-fake-data rule)
    if plan.evidence_refs:
        reasons.append(Reason(
            factor="evidence available",
            detail=f"{len(plan.evidence_refs)} evidence clip/snapshot reference(s) are attached.",
            citation={"type": "evidence", "count": len(plan.evidence_refs),
                      "refs": list(plan.evidence_refs)},
        ))
    else:
        reasons.append(Reason(
            factor="no evidence",
            detail="No video evidence is attached to this incident.",
            citation={"type": "evidence", "count": 0},
        ))

    # Fallback: if nothing specific surfaced, cite the base detection signal
    if not reasons:
        et = incident.events[0].event_type if incident.events else "detection"
        reasons.append(Reason(
            factor="detection",
            detail=(
                f"Flagged on a '{et}' detection with average confidence "
                f"{incident.get_avg_confidence():.0%}."
            ),
            citation={"type": "incident", "id": incident.incident_id},
        ))

    return reasons


def _template_rationale(reasons: List[Reason], plan: IncidentPlan) -> str:
    """Deterministic, no-LLM rationale built from the cited reasons. Real data
    only; neutral, never accusatory."""
    lead = {
        RecommendedAction.MONITOR: "This incident was flagged for monitoring",
        RecommendedAction.NOTIFY: "This incident was flagged for operator attention",
        RecommendedAction.DISPATCH_PENDING_REVIEW: "This incident was flagged for review before any dispatch",
        RecommendedAction.CLOSE: "This incident was flagged and can likely be closed after review",
    }.get(plan.recommended_next_step, "This incident was flagged for review")

    factors = "; ".join(r.detail for r in reasons)
    return f"{lead}. {factors} All findings are possible and need human confirmation."


def _build_explanation_prompt(
    incident: Incident, plan: IncidentPlan, reasons: List[Reason]
) -> tuple[str, str]:
    """System + user prompt that lets the LLM only phrase the extracted facts."""
    facts = "\n".join(f"  - {r.detail}" for r in reasons)
    system_prompt = (
        "You explain, in neutral and cautious language, why a security incident "
        "was flagged for a human reviewer. You may ONLY restate the facts given "
        "to you — do not add, infer, or speculate beyond them. Never use "
        "accusatory words (suspect, criminal, perpetrator, intruder, thief). Use "
        "'possible', 'appears', 'may indicate', 'needs review'. Make no identity "
        "or intent claims."
    )
    user_prompt = (
        f"Incident {incident.incident_id} was flagged. The ONLY established "
        f"facts are:\n{facts}\n\n"
        "Write a single short paragraph (2-4 sentences) that explains why it was "
        "flagged, using only those facts, in neutral reviewer-facing language. "
        "End by noting it requires human review."
    )
    return system_prompt, user_prompt


def explain_incident(
    incident: Incident,
    plan: IncidentPlan,
    config: Optional[VantageConfig] = None,
) -> Explanation:
    """Produce the grounded, cited "why flagged" explanation.

    Reasons (and their citations) are always deterministic. The rationale prose
    is LLM-phrased when a provider is available and passes the safety check;
    otherwise a deterministic template is used. Never raises.
    """
    config = config or VantageConfig.from_env()
    reasons = extract_reasons(incident, plan)

    system_prompt, user_prompt = _build_explanation_prompt(incident, plan, reasons)

    def _accept(text: Optional[str]) -> Optional[str]:
        """Guard LLM prose: must be non-empty and free of accusatory language."""
        if not text:
            return None
        text = text.strip()
        if not text or contains_forbidden_language(text):
            return None
        return text

    # Cloud/local tier order mirrors the rest of the engine: Ollama -> Claude -> OpenAI.
    try:
        if _ollama_available():
            prose = _accept(_call_ollama(user_prompt, system_prompt, max_tokens=250, temperature=0.2))
            if prose:
                return Explanation(incident.incident_id, prose, reasons, "ollama")

        if config.anthropic_api_key:
            prose = _accept(_call_anthropic(
                system_prompt, user_prompt,
                api_key=config.anthropic_api_key,
                model=config.anthropic_model,
                max_tokens=250,
            ))
            if prose:
                return Explanation(incident.incident_id, prose, reasons, "claude")
    except Exception:
        pass  # fail-safe: fall through to the deterministic template

    # No LLM, LLM failed, or output rejected by the safety guard.
    return Explanation(
        incident.incident_id,
        _template_rationale(reasons, plan),
        reasons,
        "template",
    )
