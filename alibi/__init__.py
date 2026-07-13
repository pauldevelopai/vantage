"""
Vantage - AI-Assisted Incident Alert Management System

This package provides incident detection, validation, and alert generation
for security camera systems with human-in-the-loop safeguards.
"""

from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentPlan,
    AlertMessage,
    ShiftReport,
    ValidationResult,
    Decision,
    IncidentStatus,
    RecommendedAction,
    ValidationStatus,
)
from alibi.alibi_engine import (
    build_incident_plan,
    validate_incident_plan,
    compile_alert,
    compile_shift_report,
)

__version__ = "1.0.0"

__all__ = [
    "CameraEvent",
    "Incident",
    "IncidentPlan",
    "AlertMessage",
    "ShiftReport",
    "ValidationResult",
    "Decision",
    "IncidentStatus",
    "RecommendedAction",
    "ValidationStatus",
    "build_incident_plan",
    "validate_incident_plan",
    "compile_alert",
    "compile_shift_report",
]
