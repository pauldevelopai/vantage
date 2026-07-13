"""
Vantage Schema Definitions

All core data structures for incident management, validation, and alerting.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from enum import Enum


class IncidentStatus(str, Enum):
    """Incident lifecycle status"""
    NEW = "new"
    TRIAGE = "triage"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"
    CLOSED = "closed"


class RecommendedAction(str, Enum):
    """Recommended next steps for incident handling"""
    MONITOR = "monitor"
    NOTIFY = "notify"
    DISPATCH_PENDING_REVIEW = "dispatch_pending_review"
    CLOSE = "close"


class ValidationStatus(str, Enum):
    """Validation result status"""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


@dataclass
class CameraEvent:
    """Individual camera detection event"""
    event_id: str
    camera_id: str
    ts: datetime  # timestamp
    zone_id: str
    event_type: str  # e.g., "person_detected", "vehicle_detected", "loitering"
    confidence: float  # 0.0 - 1.0
    severity: int  # 1-5 scale
    clip_url: Optional[str] = None
    snapshot_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)  # watchlist_match, etc.

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")
        if not 1 <= self.severity <= 5:
            raise ValueError(f"Severity must be 1-5, got {self.severity}")


@dataclass
class Incident:
    """Aggregation of related camera events"""
    incident_id: str
    status: IncidentStatus
    created_ts: datetime
    updated_ts: datetime
    events: List[CameraEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_max_severity(self) -> int:
        """Get the maximum severity across all events"""
        return max((e.severity for e in self.events), default=1)

    def get_avg_confidence(self) -> float:
        """Get average confidence across all events"""
        if not self.events:
            return 0.0
        return sum(e.confidence for e in self.events) / len(self.events)

    def has_watchlist_match(self) -> bool:
        """Check if any event has a watchlist match"""
        return any(
            e.event_type == "watchlist_match" or e.metadata.get("watchlist_match", False)
            for e in self.events
        )

    def has_evidence(self) -> bool:
        """Check if at least one event has clip or snapshot"""
        return any(
            e.clip_url or e.snapshot_url
            for e in self.events
        )


@dataclass
class IncidentPlan:
    """Analysis and recommendation for incident handling"""
    incident_id: str
    summary_1line: str
    severity: int  # 1-5
    confidence: float  # 0.0-1.0
    uncertainty_notes: str
    recommended_next_step: RecommendedAction
    requires_human_approval: bool
    action_risk_flags: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)  # URLs to clips/snapshots
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of validating an incident plan"""
    status: ValidationStatus
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertMessage:
    """Formatted alert message for operators"""
    incident_id: str
    title: str
    body: str
    operator_actions: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    disclaimer: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """Record of human operator decision on an incident"""
    incident_id: str
    decision_ts: datetime
    action_taken: str  # "dismissed", "escalated", "dispatched", etc.
    operator_notes: str
    was_true_positive: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ShiftReport:
    """Summary report for a time period"""
    start_ts: datetime
    end_ts: datetime
    incidents_summary: str
    total_incidents: int
    by_severity: Dict[int, int] = field(default_factory=dict)
    by_action: Dict[str, int] = field(default_factory=dict)
    false_positive_count: int = 0
    false_positive_notes: str = ""
    narrative: str = ""
    kpis: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
