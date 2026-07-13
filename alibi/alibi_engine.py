"""
Alibi Core Engine

Implements the schema → validate → compile → log pipeline for incident management.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from alibi.schemas import (
    Incident,
    IncidentPlan,
    AlertMessage,
    ShiftReport,
    ValidationResult,
    Decision,
    RecommendedAction,
    ValidationStatus,
)
from alibi.config import AlibiConfig, DEFAULT_CONFIG
from alibi.validator import validate_incident_plan
from alibi.llm_service import generate_alert_text, generate_shift_report_narrative


def build_incident_plan(
    incident: Incident,
    config: Optional[AlibiConfig] = None,
    context=None,
) -> IncidentPlan:
    """
    Analyze an incident and create a plan with recommendations.

    This function applies deterministic logic to assess severity, confidence,
    and recommended actions based on the incident's events.

    Args:
        incident: The incident to analyze
        config: Optional configuration (uses DEFAULT_CONFIG if not provided)
        context: Optional ContextBundle of external context. Applied
            CAUTION-ONLY: it may add risk flags or force human review, but can
            never lower severity, change the recommended action, or downgrade a
            review requirement.

    Returns:
        IncidentPlan with analysis and recommendations
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    # Aggregate metrics from events
    max_severity = incident.get_max_severity()
    avg_confidence = incident.get_avg_confidence()
    has_watchlist = incident.has_watchlist_match()
    has_evidence = incident.has_evidence()
    
    # Collect evidence references
    evidence_refs = []
    for event in incident.events:
        if event.clip_url:
            evidence_refs.append(event.clip_url)
        if event.snapshot_url:
            evidence_refs.append(event.snapshot_url)
    
    # Build uncertainty notes
    uncertainty_notes = []
    if avg_confidence < 0.9:
        uncertainty_notes.append(
            f"Average confidence is {avg_confidence:.2f} - recommend review"
        )
    if not has_evidence:
        uncertainty_notes.append("No video evidence available")
    if len(incident.events) == 1:
        uncertainty_notes.append("Single event - may be isolated false positive")
    
    # Determine recommended action based on rules
    action_risk_flags = []
    recommended_next_step = RecommendedAction.MONITOR
    requires_human_approval = False
    
    # Rule 1: Low confidence → always monitor (takes precedence)
    if avg_confidence < config.min_confidence_for_notify:
        recommended_next_step = RecommendedAction.MONITOR
        action_risk_flags.append("confidence_below_threshold")
        # Even if high severity, low confidence means monitor
        if max_severity >= config.high_severity_threshold:
            requires_human_approval = True
            action_risk_flags.append("high_severity_low_confidence")
    
    # Rule 2: Watchlist match → requires human approval and pending review
    elif has_watchlist:
        recommended_next_step = RecommendedAction.DISPATCH_PENDING_REVIEW
        requires_human_approval = True
        action_risk_flags.append("watchlist_match_requires_review")
    
    # Rule 3: High severity → requires human approval
    elif max_severity >= config.high_severity_threshold:
        recommended_next_step = RecommendedAction.DISPATCH_PENDING_REVIEW
        requires_human_approval = True
        action_risk_flags.append("high_severity_requires_review")
    
    # Rule 4: Medium confidence + medium severity → notify
    elif avg_confidence >= config.min_confidence_for_notify and max_severity >= 3:
        recommended_next_step = RecommendedAction.NOTIFY
        if not has_evidence:
            action_risk_flags.append("notify_without_evidence")
    
    # Rule 5: Low severity + reasonable confidence → close
    elif max_severity <= 2 and avg_confidence >= config.min_confidence_for_notify:
        recommended_next_step = RecommendedAction.CLOSE
    
    # Build summary
    event_types = set(e.event_type for e in incident.events)
    event_type_str = ", ".join(sorted(event_types))
    summary_1line = (
        f"{len(incident.events)} event(s) detected: {event_type_str} "
        f"(severity {max_severity}, confidence {avg_confidence:.2f})"
    )

    # Sensitive detections MUST carry neutral "possible ... / requires
    # verification" language, or the validator's hard rules reject the plan and
    # NO alert is produced for the highest-priority incidents. Keep this in sync
    # with the *_REQUIRED_PATTERNS in validator.py.
    _SENSITIVE_QUALIFIERS = {
        "watchlist_match": "possible match",
        "hotlist_plate_match": "possible match",
        "red_light_violation": "possible violation",
        "plate_vehicle_mismatch": "possible mismatch",
    }
    qualifiers = []
    if has_watchlist and "possible match" not in qualifiers:
        qualifiers.append("possible match")
    for et in sorted(event_types):
        q = _SENSITIVE_QUALIFIERS.get(et)
        if q and q not in qualifiers:
            qualifiers.append(q)
    if qualifiers:
        summary_1line += f" — {', '.join(qualifiers)}; requires verification"
    
    # Caution-only fusion of external context. Never lowers severity, never
    # changes the recommended action, never downgrades review - only tightens.
    if context is not None:
        for flag in context.caution_flags:
            if flag not in action_risk_flags:
                action_risk_flags.append(flag)
        if context.requires_review:
            requires_human_approval = True

    return IncidentPlan(
        incident_id=incident.incident_id,
        summary_1line=summary_1line,
        severity=max_severity,
        confidence=avg_confidence,
        uncertainty_notes="; ".join(uncertainty_notes) if uncertainty_notes else "None",
        recommended_next_step=recommended_next_step,
        requires_human_approval=requires_human_approval,
        action_risk_flags=action_risk_flags,
        evidence_refs=evidence_refs,
    )


def compile_alert(
    plan: IncidentPlan,
    incident: Incident,
    config: Optional[AlibiConfig] = None,
    context=None,
) -> AlertMessage:
    """
    Compile an alert message from a validated incident plan.

    Uses LLM if available, otherwise generates deterministic text.
    ALL output must be neutral and avoid accusations.

    Args:
        plan: The validated incident plan
        incident: The source incident
        config: Optional configuration
        context: Optional ContextBundle of external context. Woven into the
            narrative and stored on the incident for audit; advisory only.

    Returns:
        AlertMessage ready for operator review
    """
    if config is None:
        config = DEFAULT_CONFIG

    # Record context on the incident for the audit log (advisory provenance).
    if context is not None and not context.is_empty():
        incident.metadata["external_context"] = context.to_audit_dict()

    # Attempt LLM generation if available
    llm_result = None
    if config.openai_api_key:
        try:
            llm_result = generate_alert_text(plan, incident, config, context)
        except Exception as e:
            # Fail-safe: fall through to deterministic generation
            print(f"LLM generation failed, using fallback: {e}")

    if llm_result:
        title, body = llm_result
    else:
        # Deterministic fallback
        title = _generate_deterministic_title(plan, incident)
        body = _generate_deterministic_body(plan, incident, context)
    
    # Build operator actions
    operator_actions = []
    if plan.recommended_next_step == RecommendedAction.MONITOR:
        operator_actions.append("Continue monitoring - no immediate action required")
    elif plan.recommended_next_step == RecommendedAction.NOTIFY:
        operator_actions.append("Review incident and notify if appropriate")
    elif plan.recommended_next_step == RecommendedAction.DISPATCH_PENDING_REVIEW:
        operator_actions.append("HUMAN REVIEW REQUIRED before dispatch")
        operator_actions.append("Evaluate evidence and context")
    elif plan.recommended_next_step == RecommendedAction.CLOSE:
        operator_actions.append("Close incident - low severity/confidence")
    
    # Add disclaimer for high-risk situations
    disclaimer = ""
    if plan.requires_human_approval:
        disclaimer = (
            "⚠️ This incident requires human review before action. "
            "System recommendations are advisory only."
        )
    elif "watchlist" in str(plan.action_risk_flags).lower():
        disclaimer = (
            "⚠️ Possible watchlist match detected. Verify identity before action."
        )

    # Never let an unreachable context source read as reassurance.
    if context is not None and context.unavailable_items:
        names = ", ".join(sorted({i.label for i in context.unavailable_items}))
        note = f"ℹ️ Context source(s) could not be verified: {names}. Do not assume 'all clear'."
        disclaimer = f"{disclaimer} {note}".strip() if disclaimer else note

    return AlertMessage(
        incident_id=incident.incident_id,
        title=title,
        body=body,
        operator_actions=operator_actions,
        evidence_refs=plan.evidence_refs,
        disclaimer=disclaimer,
    )


def compile_shift_report(
    incidents: List[Incident],
    decisions: List[Decision],
    start_ts: datetime,
    end_ts: datetime,
    config: Optional[AlibiConfig] = None
) -> ShiftReport:
    """
    Compile a shift report summarizing incidents and decisions.
    
    Args:
        incidents: All incidents during the shift
        decisions: All operator decisions during the shift
        start_ts: Shift start time
        end_ts: Shift end time
        config: Optional configuration
        
    Returns:
        ShiftReport with summary and KPIs
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    # Calculate statistics
    total_incidents = len(incidents)
    by_severity = {}
    for incident in incidents:
        sev = incident.get_max_severity()
        by_severity[sev] = by_severity.get(sev, 0) + 1
    
    by_action = {}
    false_positive_count = 0
    for decision in decisions:
        by_action[decision.action_taken] = by_action.get(decision.action_taken, 0) + 1
        if not decision.was_true_positive:
            false_positive_count += 1
    
    # Calculate KPIs
    true_positive_count = len(decisions) - false_positive_count
    precision = (
        true_positive_count / len(decisions) if decisions else 0.0
    )
    
    kpis = {
        "total_incidents": total_incidents,
        "total_decisions": len(decisions),
        "true_positives": true_positive_count,
        "false_positives": false_positive_count,
        "precision": round(precision, 3),
        "avg_severity": round(
            sum(i.get_max_severity() for i in incidents) / total_incidents
            if total_incidents > 0 else 0, 2
        ),
    }
    
    # Build false positive notes
    fp_notes = []
    for decision in decisions:
        if not decision.was_true_positive and decision.operator_notes:
            fp_notes.append(f"{decision.incident_id}: {decision.operator_notes}")
    false_positive_notes = "; ".join(fp_notes) if fp_notes else "None reported"
    
    # Generate summary (use LLM if available)
    if config.openai_api_key:
        try:
            narrative = generate_shift_report_narrative(
                incidents, decisions, kpis, config
            )
        except Exception:
            narrative = _generate_deterministic_report_narrative(
                total_incidents, by_severity, by_action, kpis
            )
    else:
        narrative = _generate_deterministic_report_narrative(
            total_incidents, by_severity, by_action, kpis
        )
    
    incidents_summary = (
        f"{total_incidents} incidents processed. "
        f"Severity breakdown: " + 
        ", ".join(f"L{sev}={count}" for sev, count in sorted(by_severity.items()))
    )
    
    return ShiftReport(
        start_ts=start_ts,
        end_ts=end_ts,
        incidents_summary=incidents_summary,
        total_incidents=total_incidents,
        by_severity=by_severity,
        by_action=by_action,
        false_positive_count=false_positive_count,
        false_positive_notes=false_positive_notes,
        narrative=narrative,
        kpis=kpis,
    )


def log_incident_processing(
    incident: Incident,
    plan: IncidentPlan,
    validation: ValidationResult,
    alert: Optional[AlertMessage],
    config: Optional[AlibiConfig] = None
) -> None:
    """
    Log incident processing to append-only JSONL file.
    
    Args:
        incident: The incident
        plan: The generated plan
        validation: Validation results
        alert: The compiled alert (if validation passed)
        config: Optional configuration
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / "incident_processing.jsonl"
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "incident_id": incident.incident_id,
        "plan": {
            "summary": plan.summary_1line,
            "severity": plan.severity,
            "confidence": plan.confidence,
            "recommended_action": plan.recommended_next_step.value,
            "requires_approval": plan.requires_human_approval,
            "risk_flags": plan.action_risk_flags,
        },
        "validation": {
            "status": validation.status.value,
            "passed": validation.passed,
            "violations": validation.violations,
            "warnings": validation.warnings,
        },
        "alert_generated": alert is not None,
    }

    # Include external-context provenance if it was gathered (audit trail).
    if incident.metadata.get("external_context"):
        log_entry["external_context"] = incident.metadata["external_context"]
    
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


# Deterministic text generation helpers

def _generate_deterministic_title(plan: IncidentPlan, incident: Incident) -> str:
    """Generate a neutral, deterministic alert title"""
    action_text = {
        RecommendedAction.MONITOR: "Monitoring",
        RecommendedAction.NOTIFY: "Review Required",
        RecommendedAction.DISPATCH_PENDING_REVIEW: "Human Review Required",
        RecommendedAction.CLOSE: "Low Priority",
    }
    
    prefix = action_text.get(plan.recommended_next_step, "Alert")
    return f"{prefix}: Incident {incident.incident_id} (Severity {plan.severity})"


def _generate_deterministic_body(plan: IncidentPlan, incident: Incident, context=None) -> str:
    """Generate neutral, deterministic alert body"""
    lines = [
        f"Incident: {incident.incident_id}",
        f"Time: {incident.created_ts.strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"Summary: {plan.summary_1line}",
        f"",
        f"Assessment:",
        f"  • Severity: {plan.severity}/5",
        f"  • Confidence: {plan.confidence:.2f}",
        f"  • Events: {len(incident.events)}",
    ]

    if plan.evidence_refs:
        lines.append(f"  • Evidence: {len(plan.evidence_refs)} item(s) available")
    else:
        lines.append(f"  • Evidence: No video clips available")

    if plan.uncertainty_notes != "None":
        lines.append(f"")
        lines.append(f"Notes: {plan.uncertainty_notes}")

    if plan.action_risk_flags:
        lines.append(f"")
        lines.append(f"Risk Flags: {', '.join(plan.action_risk_flags)}")

    if context is not None and not context.is_empty():
        rendered = context.render_for_prompt()
        if rendered:
            lines.append(f"")
            lines.append(rendered)

    lines.append(f"")
    lines.append(f"Recommended Action: {plan.recommended_next_step.value}")

    return "\n".join(lines)


def _generate_deterministic_report_narrative(
    total_incidents: int,
    by_severity: dict,
    by_action: dict,
    kpis: dict
) -> str:
    """Generate deterministic shift report narrative"""
    lines = [
        f"Shift Summary:",
        f"  • Total Incidents: {total_incidents}",
        f"  • Precision: {kpis['precision']:.1%}",
        f"  • False Positives: {kpis['false_positives']}",
        f"",
        f"Severity Distribution:",
    ]
    
    for sev in sorted(by_severity.keys()):
        lines.append(f"  • Level {sev}: {by_severity[sev]} incidents")
    
    if by_action:
        lines.append(f"")
        lines.append(f"Actions Taken:")
        for action, count in sorted(by_action.items()):
            lines.append(f"  • {action}: {count}")
    
    return "\n".join(lines)
