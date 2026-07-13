"""
Regression tests: sensitive detections must produce a plan that PASSES the
validator, so an alert is actually generated.

Previously build_incident_plan emitted a bare summary with no "possible ... /
requires verification" language, so validate_incident_plan rejected every
watchlist / red-light / hotlist-plate / plate-mismatch incident and the API
(alibi_api.py: `if validation.passed: alert = compile_alert(...)`) produced NO
alert for the highest-priority detections.
"""

from datetime import datetime

import pytest

from alibi.schemas import CameraEvent, Incident, IncidentStatus
from alibi.alibi_engine import build_incident_plan
from alibi.validator import validate_incident_plan


def _incident(event_type, metadata=None, severity=4, confidence=0.85):
    ev = CameraEvent(
        event_id="e1", camera_id="cam", ts=datetime(2026, 1, 18, 2, 0),
        zone_id="z", event_type=event_type, confidence=confidence,
        severity=severity, clip_url="https://example.com/c.mp4",
        metadata=metadata or {},
    )
    return Incident("i1", IncidentStatus.NEW, ev.ts, ev.ts, [ev])


@pytest.mark.parametrize("event_type,metadata", [
    ("watchlist_match", {"watchlist_match": True}),
    ("red_light_violation", {}),
    ("hotlist_plate_match", {}),
    ("plate_vehicle_mismatch", {}),
])
def test_sensitive_detection_plan_passes_validation(event_type, metadata):
    inc = _incident(event_type, metadata)
    plan = build_incident_plan(inc)
    validation = validate_incident_plan(plan, inc)
    assert validation.passed, validation.violations
    # required neutral language present in the summary
    assert "possible" in plan.summary_1line.lower()
    assert "verification" in plan.summary_1line.lower()


def test_watchlist_via_metadata_flag_also_qualifies():
    # watchlist can be signalled by metadata rather than event_type
    inc = _incident("person_detected", {"watchlist_match": True})
    plan = build_incident_plan(inc)
    assert "possible match" in plan.summary_1line.lower()
    assert validate_incident_plan(plan, inc).passed


def test_ordinary_detection_summary_unchanged():
    inc = _incident("person_detected")
    plan = build_incident_plan(inc)
    assert "requires verification" not in plan.summary_1line.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
