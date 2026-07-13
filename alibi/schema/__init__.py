"""
Vantage Schema Module

Structured data schemas for vision-first incident management.
"""

from alibi.schema.incidents import (
    VisionIncident,
    IncidentCategory,
    DetectionSummary,
    ZoneHitSummary,
    IncidentScores,
    IncidentFlags
)

__all__ = [
    "VisionIncident",
    "IncidentCategory",
    "DetectionSummary",
    "ZoneHitSummary",
    "IncidentScores",
    "IncidentFlags"
]
