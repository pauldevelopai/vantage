# Alibi - AI-Assisted Incident Alert Management

**Alibi** is an incident detection and alert management system for security camera networks. It provides AI-assisted analysis with strict human-in-the-loop safeguards to prevent false accusations and ensure responsible automation.

## Core Philosophy

Alibi follows these principles:

1. **Never Accuse** - All output uses neutral, cautious language
2. **Human Oversight** - High-risk decisions require human approval
3. **Evidence-Based** - Actions reference video evidence or explicitly note its absence
4. **Fail-Safe** - System degrades gracefully without external dependencies
5. **Auditable** - All decisions logged in append-only format

## Architecture

Alibi uses a **schema → validate → compile → log** pipeline:

```
CameraEvents → Incident → IncidentPlan → Validation → AlertMessage → JSONL Log
                              ↓
                         (Optional LLM)
```

### Core Components

- **Schemas** (`alibi/schemas.py`) - Dataclasses for all system objects
- **Engine** (`alibi/alibi_engine.py`) - Core processing pipeline
- **Validator** (`alibi/validator.py`) - Hard safety rules enforcement
- **LLM Service** (`alibi/llm_service.py`) - Optional text generation (fail-safe)
- **Config** (`alibi/config.py`) - System configuration and thresholds

## Hard Safety Rules

These rules are **enforced with NO EXCEPTIONS**:

### Rule 1: No Accusatory Language
❌ **Forbidden**: "suspect", "criminal", "perpetrator", "intruder", "identified as"  
✅ **Required**: "possible", "appears", "may indicate", "needs review"

### Rule 2: Low Confidence → Monitor Only
If `confidence < min_confidence_for_notify` (default 0.75):
- `recommended_next_step` MUST be `"monitor"`
- No notifications or dispatch allowed

### Rule 3: High Risk → Human Approval Required
If `severity >= high_severity_threshold` (default 4) OR `watchlist_match == true`:
- `requires_human_approval` MUST be `true`
- `recommended_next_step` MUST be `"dispatch_pending_review"` (NOT "dispatch")

### Rule 4: Actions Must Reference Evidence
If `recommended_next_step` is `"notify"` or `"dispatch_pending_review"`:
- MUST have `evidence_refs` (clip/snapshot URLs) OR
- Summary MUST explicitly state "no clip available"

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Optional: Set OpenAI API key for LLM text generation
export OPENAI_API_KEY="sk-..."

# Optional: Configure thresholds
export ALIBI_MIN_CONFIDENCE_NOTIFY="0.75"
export ALIBI_HIGH_SEVERITY_THRESHOLD="4"
```

## Quick Start

```python
from datetime import datetime
from alibi import (
    CameraEvent,
    Incident,
    IncidentStatus,
    build_incident_plan,
    validate_incident_plan,
    compile_alert,
)

# 1. Create camera events
event = CameraEvent(
    event_id="evt_001",
    camera_id="cam_north_entrance",
    ts=datetime.utcnow(),
    zone_id="zone_restricted",
    event_type="person_detected",
    confidence=0.85,
    severity=3,
    clip_url="https://storage.example.com/clips/evt_001.mp4",
    snapshot_url="https://storage.example.com/snapshots/evt_001.jpg",
    metadata={"watchlist_match": False},
)

# 2. Create incident
incident = Incident(
    incident_id="inc_20260118_001",
    status=IncidentStatus.NEW,
    created_ts=datetime.utcnow(),
    updated_ts=datetime.utcnow(),
    events=[event],
)

# 3. Build incident plan
plan = build_incident_plan(incident)

print(f"Summary: {plan.summary_1line}")
print(f"Recommended Action: {plan.recommended_next_step.value}")
print(f"Requires Approval: {plan.requires_human_approval}")

# 4. Validate plan
validation = validate_incident_plan(plan, incident)

if not validation.passed:
    print("VALIDATION FAILED:")
    for violation in validation.violations:
        print(f"  - {violation}")
else:
    print("✓ Validation passed")
    
    # 5. Compile alert
    alert = compile_alert(plan, incident)
    
    print(f"\nAlert: {alert.title}")
    print(f"{alert.body}")
    
    if alert.disclaimer:
        print(f"\n{alert.disclaimer}")
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ALIBI_MIN_CONFIDENCE_NOTIFY` | 0.75 | Minimum confidence to recommend notify |
| `ALIBI_MIN_CONFIDENCE_ACTION` | 0.80 | Minimum confidence for action |
| `ALIBI_HIGH_SEVERITY_THRESHOLD` | 4 | Severity level requiring human approval |
| `OPENAI_API_KEY` | None | Optional API key for LLM text generation |
| `ALIBI_OPENAI_MODEL` | gpt-4o-mini | Model to use for text generation |
| `ALIBI_LOG_DIR` | alibi/data | Directory for JSONL logs |

### Python Configuration

```python
from alibi.config import VantageConfig

config = VantageConfig(
    min_confidence_for_notify=0.80,
    high_severity_threshold=3,
    openai_api_key="sk-...",
)

plan = build_incident_plan(incident, config)
```

## Data Schemas

### CameraEvent
Individual detection from a camera:
- `event_id`, `camera_id`, `ts`, `zone_id`
- `event_type` (e.g., "person_detected", "loitering")
- `confidence` (0.0-1.0), `severity` (1-5)
- `clip_url`, `snapshot_url` (optional)
- `metadata` (dict, can include `watchlist_match`)

### Incident
Aggregation of related events:
- `incident_id`, `status` (new|triage|dismissed|escalated|closed)
- `created_ts`, `updated_ts`
- `events` (list of CameraEvent)

### IncidentPlan
Analysis and recommendation:
- `summary_1line` - Brief description (neutral language)
- `severity` (1-5), `confidence` (0.0-1.0)
- `recommended_next_step` (monitor|notify|dispatch_pending_review|close)
- `requires_human_approval` (bool)
- `action_risk_flags` (list of warnings)
- `evidence_refs` (list of URLs)

### AlertMessage
Formatted alert for operators:
- `title`, `body` - Human-readable text
- `operator_actions` - List of recommended actions
- `evidence_refs` - Links to video/images
- `disclaimer` - Safety warnings

### ShiftReport
Summary for time period:
- `start_ts`, `end_ts`
- `incidents_summary`, `total_incidents`
- `by_severity`, `by_action` - Breakdowns
- `false_positive_count`, `false_positive_notes`
- `kpis` - Precision, true/false positive counts

## Logging

All incident processing is logged to `alibi/data/incident_processing.jsonl`:

```json
{
  "timestamp": "2026-01-18T10:30:45.123Z",
  "incident_id": "inc_20260118_001",
  "plan": {
    "summary": "1 event(s) detected: person_detected (severity 3, confidence 0.85)",
    "severity": 3,
    "confidence": 0.85,
    "recommended_action": "notify",
    "requires_approval": false,
    "risk_flags": []
  },
  "validation": {
    "status": "pass",
    "passed": true,
    "violations": [],
    "warnings": []
  },
  "alert_generated": true
}
```

## Testing

Run the comprehensive test suite:

```bash
# Run all validation tests
pytest tests/test_alibi_engine_validation.py -v

# Run specific test class
pytest tests/test_alibi_engine_validation.py::TestValidationRules -v

# Run with coverage
pytest tests/ --cov=alibi --cov-report=html
```

The test suite includes:
- 12 tests for hard safety rules
- 5 tests for engine integration
- 2 tests for language validation
- 4 tests for edge cases

## LLM Integration

Alibi can optionally use OpenAI's API to generate alert text and shift reports. This is **completely optional** and **fail-safe**:

- If `OPENAI_API_KEY` is not set, uses deterministic text generation
- If API call fails, falls back to deterministic generation
- All LLM prompts include safety instructions (neutral language, no accusations)

Example with LLM:
```python
from alibi.config import VantageConfig

config = VantageConfig(openai_api_key="sk-...")
alert = compile_alert(plan, incident, config)
# Uses LLM to generate title and body
```

Example without LLM:
```python
alert = compile_alert(plan, incident)
# Uses deterministic text generation
```

## API Reference

### `build_incident_plan(incident, config=None) -> IncidentPlan`
Analyze incident and create recommendation plan.

### `validate_incident_plan(plan, incident, config=None) -> ValidationResult`
Validate plan against hard safety rules. Returns violations if any.

### `compile_alert(plan, incident, config=None) -> AlertMessage`
Generate operator-facing alert message from validated plan.

### `compile_shift_report(incidents, decisions, start_ts, end_ts, config=None) -> ShiftReport`
Generate summary report for time period.

### `log_incident_processing(incident, plan, validation, alert, config=None)`
Append processing record to JSONL log.

## Examples

See `tests/test_alibi_engine_validation.py` for comprehensive examples of:
- Creating incidents with various severity/confidence levels
- Handling watchlist matches
- Evidence requirements
- Language validation
- Edge cases

## Migration from Newsletter System

This codebase was converted from a newsletter generation system. The old "Letter+" functionality has been **completely replaced** with Alibi. Key changes:

- ❌ Removed: Newsletter schemas, generation, publishing
- ✅ Added: Incident schemas, validation, alert compilation
- ✅ Kept: Core architecture patterns (schema → validate → compile → log)
- ✅ Kept: Optional LLM integration with fail-safe behavior

## License

See LICENSE file for details.

## Support

For issues or questions, please file an issue on the repository.
