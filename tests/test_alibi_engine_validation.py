"""
Comprehensive validation tests for Alibi engine.

Tests all hard safety rules with NO EXCEPTIONS.
"""

import pytest
from datetime import datetime, timedelta

from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentPlan,
    IncidentStatus,
    RecommendedAction,
    ValidationStatus,
)
from alibi.config import VantageConfig
from alibi.alibi_engine import build_incident_plan
from alibi.validator import (
    validate_incident_plan,
    contains_forbidden_language,
    suggest_neutral_alternative,
)


# Test fixtures

def create_test_event(
    event_id: str = "evt_001",
    confidence: float = 0.85,
    severity: int = 3,
    event_type: str = "person_detected",
    watchlist_match: bool = False,
    clip_url: str = None,
) -> CameraEvent:
    """Helper to create test camera events"""
    return CameraEvent(
        event_id=event_id,
        camera_id="cam_01",
        ts=datetime.utcnow(),
        zone_id="zone_north",
        event_type=event_type,
        confidence=confidence,
        severity=severity,
        clip_url=clip_url,
        snapshot_url=f"https://example.com/snapshot/{event_id}.jpg" if clip_url else None,
        metadata={"watchlist_match": watchlist_match},
    )


def create_test_incident(
    incident_id: str = "inc_001",
    events: list = None,
) -> Incident:
    """Helper to create test incidents"""
    if events is None:
        events = [create_test_event()]
    
    return Incident(
        incident_id=incident_id,
        status=IncidentStatus.NEW,
        created_ts=datetime.utcnow(),
        updated_ts=datetime.utcnow(),
        events=events,
    )


# Test Suite

class TestValidationRules:
    """Test hard safety rules enforcement"""
    
    def test_rule1_forbidden_language_suspect(self):
        """Rule 1: Reject accusatory language - 'suspect'"""
        incident = create_test_incident()
        
        # Manually create plan with forbidden language
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Suspect detected entering building",
            severity=3,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident)
        
        assert not validation.passed
        assert validation.status == ValidationStatus.FAIL
        assert any("accusatory" in v.lower() for v in validation.violations)
    
    def test_rule1_forbidden_language_criminal(self):
        """Rule 1: Reject accusatory language - 'criminal'"""
        incident = create_test_incident()
        
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Criminal activity detected",
            severity=3,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident)
        
        assert not validation.passed
        assert any("accusatory" in v.lower() for v in validation.violations)
    
    def test_rule1_neutral_language_passes(self):
        """Rule 1: Accept neutral language"""
        incident = create_test_incident()
        
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Possible unauthorized access detected, needs review",
            severity=3,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident)
        
        # Should pass (no forbidden language)
        assert validation.passed
    
    def test_rule2_low_confidence_must_monitor(self):
        """Rule 2: Low confidence MUST recommend 'monitor'"""
        event = create_test_event(confidence=0.65)
        incident = create_test_incident(events=[event])
        
        # Try to create plan that violates rule
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Low confidence event",
            severity=2,
            confidence=0.65,
            uncertainty_notes="Low confidence",
            recommended_next_step=RecommendedAction.NOTIFY,  # WRONG!
            requires_human_approval=False,
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident)
        
        assert not validation.passed
        assert any("confidence" in v.lower() and "monitor" in v.lower() 
                   for v in validation.violations)
    
    def test_rule2_low_confidence_engine_behavior(self):
        """Rule 2: Engine should automatically recommend monitor for low confidence"""
        event = create_test_event(confidence=0.65)
        incident = create_test_incident(events=[event])
        
        config = VantageConfig(min_confidence_for_notify=0.75)
        plan = build_incident_plan(incident, config)
        
        # Engine should automatically set monitor
        assert plan.recommended_next_step == RecommendedAction.MONITOR
        
        # Validation should pass
        validation = validate_incident_plan(plan, incident, config)
        assert validation.passed
    
    def test_rule3a_high_severity_requires_approval(self):
        """Rule 3a: High severity MUST require human approval"""
        event = create_test_event(severity=5, confidence=0.85)
        incident = create_test_incident(events=[event])
        
        config = VantageConfig(high_severity_threshold=4)
        
        # Manually create plan that violates rule
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="High severity event detected",
            severity=5,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,  # WRONG!
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident, config)
        
        assert not validation.passed
        assert any("severity" in v.lower() and "approval" in v.lower() 
                   for v in validation.violations)
    
    def test_rule3a_high_severity_must_dispatch_pending(self):
        """Rule 3a: High severity must recommend dispatch_pending_review"""
        event = create_test_event(severity=5, confidence=0.85)
        incident = create_test_incident(events=[event])
        
        config = VantageConfig(high_severity_threshold=4)
        
        # Create plan with wrong action
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="High severity event",
            severity=5,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,  # Should be DISPATCH_PENDING_REVIEW
            requires_human_approval=True,
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident, config)
        
        assert not validation.passed
        assert any("dispatch_pending_review" in v.lower() for v in validation.violations)
    
    def test_rule3b_watchlist_requires_approval(self):
        """Rule 3b: Watchlist match MUST require human approval"""
        event = create_test_event(
            confidence=0.85,
            severity=3,
            watchlist_match=True
        )
        incident = create_test_incident(events=[event])
        
        # Create plan without approval
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Possible match detected",
            severity=3,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,  # WRONG!
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident)
        
        assert not validation.passed
        assert any("watchlist" in v.lower() for v in validation.violations)
    
    def test_rule3b_watchlist_engine_behavior(self):
        """Rule 3b: Engine should handle watchlist matches correctly"""
        event = create_test_event(
            confidence=0.85,
            severity=3,
            watchlist_match=True,
            clip_url="https://example.com/clip1.mp4"
        )
        incident = create_test_incident(events=[event])
        
        plan = build_incident_plan(incident)
        
        # Engine should set these automatically
        assert plan.requires_human_approval is True
        assert plan.recommended_next_step == RecommendedAction.DISPATCH_PENDING_REVIEW
        
        validation = validate_incident_plan(plan, incident)
        assert validation.passed
    
    def test_rule4_notify_requires_evidence_or_mention(self):
        """Rule 4: Notify/dispatch must have evidence OR mention absence"""
        # Create event without evidence
        event = create_test_event(
            confidence=0.85,
            severity=3,
            clip_url=None  # No evidence!
        )
        event.snapshot_url = None
        incident = create_test_incident(events=[event])
        
        # Plan recommends notify but doesn't mention lack of evidence
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Event detected",  # No mention of "no clip"
            severity=3,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,
            evidence_refs=[],  # Empty!
        )
        
        validation = validate_incident_plan(plan, incident)
        
        assert not validation.passed
        assert any("evidence" in v.lower() or "clip" in v.lower() 
                   for v in validation.violations)
    
    def test_rule4_notify_with_evidence_refs_passes(self):
        """Rule 4: Notify with evidence references passes"""
        event = create_test_event(
            confidence=0.85,
            severity=3,
            clip_url="https://example.com/clip1.mp4"
        )
        incident = create_test_incident(events=[event])
        
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Event detected with video",
            severity=3,
            confidence=0.85,
            uncertainty_notes="None",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,
            evidence_refs=["https://example.com/clip1.mp4"],
        )
        
        validation = validate_incident_plan(plan, incident)
        assert validation.passed
    
    def test_rule4_notify_with_no_clip_mention_passes(self):
        """Rule 4: Notify without evidence but with explicit mention passes"""
        event = create_test_event(
            confidence=0.85,
            severity=3,
            clip_url=None
        )
        event.snapshot_url = None
        incident = create_test_incident(events=[event])
        
        plan = IncidentPlan(
            incident_id=incident.incident_id,
            summary_1line="Event detected, no clip available",  # Explicit mention!
            severity=3,
            confidence=0.85,
            uncertainty_notes="No video evidence",
            recommended_next_step=RecommendedAction.NOTIFY,
            requires_human_approval=False,
            evidence_refs=[],
        )
        
        validation = validate_incident_plan(plan, incident)
        assert validation.passed


class TestEngineIntegration:
    """Test that engine follows rules correctly"""
    
    def test_engine_handles_low_confidence(self):
        """Engine should automatically handle low confidence correctly"""
        event = create_test_event(confidence=0.60, severity=4)
        incident = create_test_incident(events=[event])
        
        config = VantageConfig(min_confidence_for_notify=0.75)
        plan = build_incident_plan(incident, config)
        validation = validate_incident_plan(plan, incident, config)
        
        assert plan.recommended_next_step == RecommendedAction.MONITOR
        assert validation.passed
    
    def test_engine_handles_high_severity(self):
        """Engine should handle high severity with approval"""
        event = create_test_event(
            confidence=0.90,
            severity=5,
            clip_url="https://example.com/clip1.mp4"
        )
        incident = create_test_incident(events=[event])
        
        config = VantageConfig(high_severity_threshold=4)
        plan = build_incident_plan(incident, config)
        validation = validate_incident_plan(plan, incident, config)
        
        assert plan.requires_human_approval is True
        assert plan.recommended_next_step == RecommendedAction.DISPATCH_PENDING_REVIEW
        assert validation.passed
    
    def test_engine_handles_watchlist_match(self):
        """Engine should handle watchlist matches correctly"""
        event = create_test_event(
            confidence=0.80,
            severity=3,
            watchlist_match=True,
            clip_url="https://example.com/clip1.mp4"
        )
        incident = create_test_incident(events=[event])
        
        plan = build_incident_plan(incident)
        validation = validate_incident_plan(plan, incident)
        
        assert plan.requires_human_approval is True
        assert plan.recommended_next_step == RecommendedAction.DISPATCH_PENDING_REVIEW
        assert validation.passed
    
    def test_engine_handles_medium_case(self):
        """Engine should handle medium severity/confidence"""
        event = create_test_event(
            confidence=0.80,
            severity=3,
            clip_url="https://example.com/clip1.mp4"
        )
        incident = create_test_incident(events=[event])
        
        plan = build_incident_plan(incident)
        validation = validate_incident_plan(plan, incident)
        
        assert plan.recommended_next_step == RecommendedAction.NOTIFY
        assert validation.passed
    
    def test_engine_handles_low_severity_close(self):
        """Engine should recommend close for low severity with good confidence"""
        event = create_test_event(
            confidence=0.80,  # Need >= min_confidence_for_notify
            severity=2,
        )
        incident = create_test_incident(events=[event])
        
        plan = build_incident_plan(incident)
        validation = validate_incident_plan(plan, incident)
        
        assert plan.recommended_next_step == RecommendedAction.CLOSE
        assert validation.passed


class TestLanguageValidation:
    """Test language validation helpers"""
    
    def test_contains_forbidden_language(self):
        """Test detection of forbidden patterns"""
        assert contains_forbidden_language("The suspect was seen entering")
        assert contains_forbidden_language("Criminal activity detected")
        assert contains_forbidden_language("Identified as John Doe")
        assert contains_forbidden_language("The perpetrator is guilty")
        
        # Neutral language should pass
        assert not contains_forbidden_language("Possible unauthorized access")
        assert not contains_forbidden_language("Person appears to be entering")
        assert not contains_forbidden_language("Needs review by operator")
    
    def test_suggest_neutral_alternative(self):
        """Test neutral language suggestions"""
        result = suggest_neutral_alternative("Suspect detected")
        assert "suspect" not in result.lower()
        assert "person" in result.lower()
        
        result = suggest_neutral_alternative("Criminal activity")
        assert "criminal" not in result.lower()
        
        result = suggest_neutral_alternative("Identified as John")
        assert "identified as" not in result.lower()
        assert "match" in result.lower()


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_zero_events(self):
        """Handle incident with no events"""
        incident = create_test_incident(events=[])
        
        plan = build_incident_plan(incident)
        
        assert plan.severity == 1
        assert plan.confidence == 0.0
        # Zero confidence means monitor (not close)
        assert plan.recommended_next_step == RecommendedAction.MONITOR
    
    def test_multiple_events_aggregation(self):
        """Test aggregation of multiple events"""
        events = [
            create_test_event("evt1", confidence=0.80, severity=3, clip_url="http://clip1.mp4"),
            create_test_event("evt2", confidence=0.90, severity=4, clip_url="http://clip2.mp4"),
            create_test_event("evt3", confidence=0.85, severity=3, clip_url="http://clip3.mp4"),
        ]
        incident = create_test_incident(events=events)
        
        plan = build_incident_plan(incident)
        
        assert plan.severity == 4  # Max
        assert 0.80 <= plan.confidence <= 0.90  # Average
        assert len(plan.evidence_refs) > 0  # Should have clips
    
    def test_confidence_boundary(self):
        """Test confidence exactly at threshold"""
        config = VantageConfig(min_confidence_for_notify=0.75)
        
        # Just below threshold
        event = create_test_event(confidence=0.74, severity=3)
        incident = create_test_incident(events=[event])
        plan = build_incident_plan(incident, config)
        assert plan.recommended_next_step == RecommendedAction.MONITOR
        
        # At threshold
        event = create_test_event(confidence=0.75, severity=3, clip_url="http://clip.mp4")
        incident = create_test_incident(events=[event])
        plan = build_incident_plan(incident, config)
        assert plan.recommended_next_step == RecommendedAction.NOTIFY
    
    def test_severity_boundary(self):
        """Test severity exactly at threshold"""
        config = VantageConfig(high_severity_threshold=4)
        
        # Just below threshold
        event = create_test_event(confidence=0.85, severity=3, clip_url="http://clip.mp4")
        incident = create_test_incident(events=[event])
        plan = build_incident_plan(incident, config)
        assert not plan.requires_human_approval
        
        # At threshold
        event = create_test_event(confidence=0.85, severity=4, clip_url="http://clip.mp4")
        incident = create_test_incident(events=[event])
        plan = build_incident_plan(incident, config)
        assert plan.requires_human_approval


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
