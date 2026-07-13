# Alibi - AI-Assisted Incident Alert Management

**Alibi** is an incident detection and alert management system for security camera networks. It provides AI-assisted analysis with strict human-in-the-loop safeguards to prevent false accusations and ensure responsible automation.

## 🔒 Core Philosophy

1. **Never Accuse** - All output uses neutral, cautious language
2. **Human Oversight** - High-risk decisions require human approval  
3. **Evidence-Based** - Actions reference video evidence or explicitly note its absence
4. **Fail-Safe** - System degrades gracefully without external dependencies
5. **Auditable** - All decisions logged in append-only format

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the demo
python alibi/demo.py

# Run tests
pytest tests/test_alibi_engine_validation.py -v
```

## 📋 Hard Safety Rules

These rules are **enforced with NO EXCEPTIONS**:

### Rule 1: No Accusatory Language
❌ **Forbidden**: "suspect", "criminal", "perpetrator", "intruder"  
✅ **Required**: "possible", "appears", "may indicate", "needs review"

### Rule 2: Low Confidence → Monitor Only
If confidence < 0.75 (configurable):
- Recommended action MUST be "monitor"
- No notifications or dispatch allowed

### Rule 3: High Risk → Human Approval Required  
If severity ≥ 4 OR watchlist match:
- `requires_human_approval` MUST be true
- Action MUST be "dispatch_pending_review" (NOT "dispatch")

### Rule 4: Actions Must Reference Evidence
If recommending "notify" or "dispatch":
- MUST have evidence references (clip/snapshot URLs) OR
- Summary MUST explicitly state "no clip available"

## 🏗️ Architecture

```
CameraEvents → Incident → IncidentPlan → Validation → AlertMessage → JSONL Log
                              ↓
                         (Optional LLM)
```

### Core Components

- **`alibi/schemas.py`** - Dataclasses for all system objects
- **`alibi/alibi_engine.py`** - Core processing pipeline
- **`alibi/validator.py`** - Hard safety rules enforcement
- **`alibi/llm_service.py`** - Optional text generation (fail-safe)
- **`alibi/config.py`** - System configuration and thresholds

## 📊 Example Usage

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

# Create camera event
event = CameraEvent(
    event_id="evt_001",
    camera_id="cam_north",
    ts=datetime.utcnow(),
    zone_id="zone_restricted",
    event_type="person_detected",
    confidence=0.85,
    severity=3,
    clip_url="https://storage.example.com/clips/evt_001.mp4",
    metadata={"watchlist_match": False},
)

# Create incident
incident = Incident(
    incident_id="inc_001",
    status=IncidentStatus.NEW,
    created_ts=datetime.utcnow(),
    updated_ts=datetime.utcnow(),
    events=[event],
)

# Build and validate plan
plan = build_incident_plan(incident)
validation = validate_incident_plan(plan, incident)

if validation.passed:
    alert = compile_alert(plan, incident)
    print(f"Alert: {alert.title}")
    print(f"Action: {plan.recommended_next_step.value}")
else:
    print("Validation failed:")
    for violation in validation.violations:
        print(f"  - {violation}")
```

## 🧪 Testing

All 23 tests pass, covering:

- ✅ 12 tests for hard safety rules
- ✅ 5 tests for engine integration  
- ✅ 2 tests for language validation
- ✅ 4 tests for edge cases

```bash
pytest tests/test_alibi_engine_validation.py -v
```

## 🔧 Configuration

```bash
# Environment variables
export ALIBI_MIN_CONFIDENCE_NOTIFY="0.75"
export ALIBI_HIGH_SEVERITY_THRESHOLD="4"
export OPENAI_API_KEY="sk-..."  # Optional for LLM text generation
```

Or in Python:

```python
from alibi.config import VantageConfig

config = VantageConfig(
    min_confidence_for_notify=0.80,
    high_severity_threshold=3,
    openai_api_key="sk-...",
)
```

## 📝 Logging

All incident processing is logged to `alibi/data/incident_processing.jsonl`:

```json
{
  "timestamp": "2026-01-18T10:30:45.123Z",
  "incident_id": "inc_001",
  "plan": {
    "summary": "1 event(s) detected: person_detected (severity 3, confidence 0.85)",
    "severity": 3,
    "confidence": 0.85,
    "recommended_action": "notify",
    "requires_approval": false
  },
  "validation": {
    "status": "pass",
    "passed": true,
    "violations": []
  },
  "alert_generated": true
}
```

## 🤖 Optional LLM Integration

Alibi can use OpenAI's API for text generation, but it's **completely optional** and **fail-safe**:

- If `OPENAI_API_KEY` is not set → uses deterministic text
- If API call fails → falls back to deterministic text
- All LLM prompts include safety instructions

## 📚 Documentation

See **`alibi/README.md`** for comprehensive documentation including:

- Detailed API reference
- All data schemas
- Configuration options
- Migration notes from newsletter system

## 🔄 Migration from Newsletter System

This codebase was converted from a newsletter generation system (Letter+). The old functionality has been **completely replaced** with Alibi:

- ❌ Removed: Newsletter schemas, generation, publishing
- ✅ Added: Incident schemas, validation, alert compilation
- ✅ Kept: Core architecture patterns (schema → validate → compile → log)
- ✅ Kept: Optional LLM integration with fail-safe behavior

## 📄 License

See LICENSE file for details.

## 🆘 Support

For issues or questions, please file an issue on the repository.

---

**Built with safety-first principles for responsible AI-assisted security operations.**
