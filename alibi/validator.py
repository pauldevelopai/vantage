"""
Vantage Validation Logic

Hard safety rules enforced with NO EXCEPTIONS.
"""

from typing import Optional
import re

from alibi.schemas import (
    Incident,
    IncidentPlan,
    ValidationResult,
    ValidationStatus,
    RecommendedAction,
)
from alibi.config import VantageConfig, DEFAULT_CONFIG


# Forbidden patterns that indicate accusations or identity claims
FORBIDDEN_PATTERNS = [
    r'\b(suspect|perpetrator|criminal|intruder|burglar|thief)\b',
    r'\b(identified as|confirms identity|is definitely|confirmed as)\b',
    r'\b(guilty|caught|breaking in)\b',
    r'\b(this person is|the individual is|this is)\b',
    r'\b(match confirmed|positive identification|identified the person)\b',
]

# Watchlist-specific forbidden patterns
WATCHLIST_FORBIDDEN_PATTERNS = [
    r'\b(is|are)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b',  # "is John Doe"
    r'\b(identified|confirmed|verified)\s+(as|to be)\b',
    r'\bwatchlist\s+(hit|confirmation|identification)\b',
]

# Required watchlist language
WATCHLIST_REQUIRED_PATTERNS = [
    r'\b(possible|potential|may be|appears to be)\b',
    r'\b(requires? (verification|review|confirmation))\b',
]

# Red light violation forbidden patterns
RED_LIGHT_FORBIDDEN_PATTERNS = [
    r'\b(definite|confirmed|certain)\s+violation\b',
    r'\b(guilty|at fault|committed)\b',
    r'\b(will be cited|citation issued)\b',
]

# Required red light language
RED_LIGHT_REQUIRED_PATTERNS = [
    r'\b(possible|potential|appears?|may be)\b',
    r'\b(verify|review|confirm)\b',
]

# Hotlist plate forbidden patterns
HOTLIST_PLATE_FORBIDDEN_PATTERNS = [
    r'\b(confirmed|verified|definite)\s+(stolen|hotlist)\b',
    r'\b(impound|seize|arrest)\b',
    r'\b(is stolen|was stolen)\b',
]

# Required hotlist plate language
HOTLIST_PLATE_REQUIRED_PATTERNS = [
    r'\b(possible|potential|appears?|may be)\b',
    r'\b(verify|review|confirm)\b',
]

# Plate-vehicle mismatch forbidden patterns
MISMATCH_FORBIDDEN_PATTERNS = [
    r'\b(confirmed|verified|definite)\s+(mismatch|stolen|swapped)\b',
    r'\b(is stolen|was stolen|is swapped)\b',
    r'\b(impound|seize|arrest)\b',
    r'\b(fraud|crime|illegal)\b',
]

# Required mismatch language
MISMATCH_REQUIRED_PATTERNS = [
    r'\b(possible|potential|appears?|may be)\b',
    r'\b(verify|review|confirm)\b',
    r'\bmismatch\b',
]

# Required neutral language patterns
NEUTRAL_PATTERNS = [
    r'\b(possible|appears|may be|potential|suggests)\b',
    r'\b(needs review|requires review|recommend review)\b',
]


def validate_incident_plan(
    plan: IncidentPlan,
    incident: Incident,
    config: Optional[VantageConfig] = None
) -> ValidationResult:
    """
    Validate incident plan against hard safety rules.
    
    NO EXCEPTIONS to these rules:
    1. No accusations or identity claims - use neutral language
    2. Low confidence → recommended_next_step MUST be "monitor"
    3. High severity OR watchlist → requires_human_approval MUST be True
       and next step MUST be "dispatch_pending_review" (not dispatch)
    4. Any "notify" or "dispatch_pending_review" MUST have evidence
       OR explicitly state "no clip available"
    
    Args:
        plan: The incident plan to validate
        incident: The source incident
        config: Optional configuration
        
    Returns:
        ValidationResult with pass/fail and any violations
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    violations = []
    warnings = []
    
    # Rule 1: Check for accusatory language in summary
    summary_lower = plan.summary_1line.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, summary_lower, re.IGNORECASE):
            violations.append(
                f"VIOLATION: Accusatory language detected in summary. "
                f"Pattern: {pattern}. Use neutral terms like 'possible', 'appears', etc."
            )
    
    # Rule 2: Low confidence MUST recommend "monitor"
    if plan.confidence < config.min_confidence_for_notify:
        if plan.recommended_next_step != RecommendedAction.MONITOR:
            violations.append(
                f"VIOLATION: Confidence {plan.confidence:.2f} is below threshold "
                f"{config.min_confidence_for_notify}. "
                f"Recommended action MUST be 'monitor', got '{plan.recommended_next_step.value}'"
            )
    
    # Rule 3a: High severity MUST require human approval
    if plan.severity >= config.high_severity_threshold:
        if not plan.requires_human_approval:
            violations.append(
                f"VIOLATION: Severity {plan.severity} >= {config.high_severity_threshold} "
                f"MUST set requires_human_approval=True"
            )
        if plan.recommended_next_step not in [
            RecommendedAction.MONITOR,
            RecommendedAction.DISPATCH_PENDING_REVIEW
        ]:
            violations.append(
                f"VIOLATION: Severity {plan.severity} >= {config.high_severity_threshold} "
                f"MUST recommend 'dispatch_pending_review' (not 'dispatch'), "
                f"got '{plan.recommended_next_step.value}'"
            )
    
    # Rule 3b: Watchlist match MUST require human approval
    if incident.has_watchlist_match():
        if not plan.requires_human_approval:
            violations.append(
                "VIOLATION: Watchlist match detected. "
                "MUST set requires_human_approval=True"
            )
        if plan.recommended_next_step not in [
            RecommendedAction.MONITOR,
            RecommendedAction.DISPATCH_PENDING_REVIEW
        ]:
            violations.append(
                "VIOLATION: Watchlist match detected. "
                f"MUST recommend 'dispatch_pending_review', "
                f"got '{plan.recommended_next_step.value}'"
            )
        
        # Rule 3c: Watchlist alerts MUST use "possible match" language
        for pattern in WATCHLIST_FORBIDDEN_PATTERNS:
            if re.search(pattern, summary_lower, re.IGNORECASE):
                violations.append(
                    f"VIOLATION: Watchlist alert contains forbidden identity claim. "
                    f"Pattern: {pattern}. MUST use 'possible match' language only."
                )
        
        # Check for required neutral language
        has_required_language = any(
            re.search(pattern, summary_lower, re.IGNORECASE)
            for pattern in WATCHLIST_REQUIRED_PATTERNS
        )
        if not has_required_language:
            violations.append(
                "VIOLATION: Watchlist alert MUST include 'possible match' or "
                "'requires verification' language. Never state identity as fact."
            )
    
    # Rule 3d: Red light violations MUST use "possible violation" language
    if any(event.event_type == "red_light_violation" for event in incident.events):
        for pattern in RED_LIGHT_FORBIDDEN_PATTERNS:
            if re.search(pattern, summary_lower, re.IGNORECASE):
                violations.append(
                    f"VIOLATION: Red light alert contains forbidden certainty claim. "
                    f"Pattern: {pattern}. MUST use 'possible violation' language only."
                )
        
        # Check for required neutral language
        has_required_language = any(
            re.search(pattern, summary_lower, re.IGNORECASE)
            for pattern in RED_LIGHT_REQUIRED_PATTERNS
        )
        if not has_required_language:
            violations.append(
                "VIOLATION: Red light alert MUST include 'possible violation' or "
                "'requires verification' language. Never state violation as fact."
            )
        
        # Red light violations MUST require human approval
        if not plan.requires_human_approval:
            violations.append(
                "VIOLATION: Red light violation detected. "
                "MUST set requires_human_approval=True"
            )
    
    # Rule 3e: Hotlist plate matches MUST use "possible match" language
    if any(event.event_type == "hotlist_plate_match" for event in incident.events):
        for pattern in HOTLIST_PLATE_FORBIDDEN_PATTERNS:
            if re.search(pattern, summary_lower, re.IGNORECASE):
                violations.append(
                    f"VIOLATION: Hotlist plate alert contains forbidden certainty claim. "
                    f"Pattern: {pattern}. MUST use 'possible match' language only."
                )
        
        # Check for required neutral language
        has_required_language = any(
            re.search(pattern, summary_lower, re.IGNORECASE)
            for pattern in HOTLIST_PLATE_REQUIRED_PATTERNS
        )
        if not has_required_language:
            violations.append(
                "VIOLATION: Hotlist plate alert MUST include 'possible match' or "
                "'requires verification' language. Never state as fact."
            )
        
        # Hotlist plate matches MUST require human approval
        if not plan.requires_human_approval:
            violations.append(
                "VIOLATION: Hotlist plate match detected. "
                "MUST set requires_human_approval=True"
            )
    
    # Rule 3f: Plate-vehicle mismatch MUST use "possible mismatch" language
    if any(event.event_type == "plate_vehicle_mismatch" for event in incident.events):
        for pattern in MISMATCH_FORBIDDEN_PATTERNS:
            if re.search(pattern, summary_lower, re.IGNORECASE):
                violations.append(
                    f"VIOLATION: Mismatch alert contains forbidden certainty claim. "
                    f"Pattern: {pattern}. MUST use 'possible mismatch' language only."
                )
        
        # Check for required neutral language
        has_required_language = any(
            re.search(pattern, summary_lower, re.IGNORECASE)
            for pattern in MISMATCH_REQUIRED_PATTERNS
        )
        if not has_required_language:
            violations.append(
                "VIOLATION: Mismatch alert MUST include 'possible mismatch' or "
                "'requires verification' language. Never state as fact."
            )
        
        # Mismatch alerts MUST require human approval
        if not plan.requires_human_approval:
            violations.append(
                "VIOLATION: Plate-vehicle mismatch detected. "
                "MUST set requires_human_approval=True"
            )
        
        # Mismatch should recommend dispatch_pending_review
        if plan.recommended_next_step != RecommendedAction.DISPATCH_PENDING_REVIEW:
            warnings.append(
                "WARNING: Mismatch alerts should recommend dispatch_pending_review. "
                f"Current: {plan.recommended_next_step}"
            )
    
    # Rule 4: Notify/dispatch actions MUST reference evidence or state absence
    if plan.recommended_next_step in [
        RecommendedAction.NOTIFY,
        RecommendedAction.DISPATCH_PENDING_REVIEW
    ]:
        has_evidence_refs = len(plan.evidence_refs) > 0
        mentions_no_evidence = (
            "no clip" in summary_lower or
            "no video" in summary_lower or
            "no evidence" in summary_lower or
            "no snapshot" in summary_lower
        )
        
        if not has_evidence_refs and not mentions_no_evidence:
            violations.append(
                f"VIOLATION: Action '{plan.recommended_next_step.value}' "
                f"requires either evidence references OR explicit mention of "
                f"'no clip available' in summary"
            )
    
    # Warnings (not violations, but recommended)
    
    # Warn if no neutral language detected in summary
    has_neutral = any(
        re.search(pattern, summary_lower, re.IGNORECASE)
        for pattern in NEUTRAL_PATTERNS
    )
    if not has_neutral and plan.severity >= 3:
        warnings.append(
            "WARNING: Consider using neutral language like 'possible', 'appears', "
            "'may indicate' in summary for severity >= 3"
        )
    
    # Warn if uncertainty_notes is empty but confidence < 0.8
    if plan.confidence < 0.8 and plan.uncertainty_notes == "None":
        warnings.append(
            f"WARNING: Confidence is {plan.confidence:.2f} but no uncertainty notes provided"
        )
    
    # Warn if high severity but no risk flags
    if plan.severity >= 4 and not plan.action_risk_flags:
        warnings.append(
            f"WARNING: Severity {plan.severity} but no action_risk_flags set"
        )
    
    # Determine overall status
    passed = len(violations) == 0
    status = ValidationStatus.PASS if passed else ValidationStatus.FAIL
    
    if not passed:
        status = ValidationStatus.FAIL
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASS
    
    return ValidationResult(
        status=status,
        passed=passed,
        violations=violations,
        warnings=warnings,
        metadata={
            "confidence": plan.confidence,
            "severity": plan.severity,
            "requires_approval": plan.requires_human_approval,
        }
    )


def contains_forbidden_language(text: str) -> bool:
    """
    Check if text contains forbidden accusatory language.
    
    Args:
        text: Text to check
        
    Returns:
        True if forbidden patterns found, False otherwise
    """
    text_lower = text.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def suggest_neutral_alternative(text: str) -> str:
    """
    Suggest neutral alternative for accusatory text.
    
    Args:
        text: Text with potential accusatory language
        
    Returns:
        Suggested neutral alternative
    """
    # Simple replacements for common violations
    replacements = {
        r'\bsuspect\b': 'person of interest',
        r'\bperpetrator\b': 'individual',
        r'\bcriminal\b': 'person detected',
        r'\bintruder\b': 'unauthorized person possibly detected',
        r'\bburglar\b': 'person detected in restricted area',
        r'\bthief\b': 'person detected',
        r'\bidentified as\b': 'appears to match',
        r'\bconfirms identity\b': 'suggests possible match',
        r'\bis definitely\b': 'appears to be',
        r'\bguilty\b': 'suspected of',
        r'\bcaught\b': 'detected',
        r'\bbreaking in\b': 'entering unauthorized',
    }
    
    result = text
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result
