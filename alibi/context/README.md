# External-Data Fusion for the Advisor (`alibi.context`)

Bundles non-video context (activity baselines, prior intelligence, known-person
matches, and later: access logs, shift schedules, weather, area alerts) into the
incident advisor — the LLM narrative the operator reads, plus a **caution-only**
signal path.

## The one rule that governs this package

Deterministic safety rules decide the action; context only informs and tightens.

Context can:
- appear in the alert narrative and the audit log, and
- **add a risk flag** or **force human review** (caution-only).

Context can **never**:
- lower severity, change the recommended action, or downgrade a review
  requirement, and
- be attributed to the detected individual (it is *area/facility* context).

This is enforced in `alibi_engine.build_incident_plan`: it only ever appends
`context.caution_flags` and OR-s in `context.requires_review`.

## Three-state, never "silently all clear"

Every `ContextItem` is `PRESENT` / `ABSENT` / `UNAVAILABLE`.

- `ABSENT` = source reached, nothing on record.
- `UNAVAILABLE` = source could NOT be checked (down / not configured / errored).

`UNAVAILABLE` is surfaced to the operator (prompt + disclaimer) so a broken feed
never reads as reassurance. **No fake data, ever** — a provider that cannot reach
its source returns `UNAVAILABLE` or raises; it must not invent an "all clear".

## Providers shipped now (real data, no integrations)

| Provider | Source | Caution signal |
|----------|--------|----------------|
| `BaselineContextProvider` | `activity_baseline.py` (learned per-camera/hour norm) | `activity_anomaly_vs_baseline` → forces review |
| `IntelligenceContextProvider` | `intelligence_store.py` (operator red flags / high-risk places) | `prior_high_risk_flag_this_area`, `high_risk_location` → forces review |
| `KnownPersonsContextProvider` | `known_persons.py` (upstream ReID match) | `known_person_on_watch` → forces review. Trusted match = info only, never de-escalates |

## Adding an external adapter (access logs, schedules, weather, alerts)

Subclass `ContextProvider`, return `ContextItem`s, and register it. The builder
runs providers fail-safe (an exception becomes one `UNAVAILABLE` item) and passes
every string through the accusatory-language guard before it reaches the prompt.

```python
from alibi.context import ContextProvider, ContextItem, Availability

class AccessLogProvider(ContextProvider):
    name = "access_control"

    def fetch(self, incident, config=None):
        camera, zone, ts = latest_camera_and_ts(incident)  # from providers._incident_signals
        try:
            rows = read_access_log(...)          # a REAL operator-provided file / API
        except Exception:
            # not reachable -> honest UNAVAILABLE, never a fabricated "no entries"
            return [ContextItem(self.name, "Access control",
                                Availability.UNAVAILABLE, source="access log")]
        recent = [r for r in rows if near(r, zone, ts)]
        if not recent:
            return [ContextItem(self.name, "Access control",
                                Availability.ABSENT, source="access log")]
        return [ContextItem(
            self.name, "Access control", Availability.PRESENT,
            summary=f"{len(recent)} badge event(s) at this zone around this time.",
            source="access log", as_of=ts,
            caution_signals=["no_matching_badge_event"] if unexpected(recent) else [],
            elevate_review=unexpected(recent),
        )]
```

Then pass it in: `build_context(incident, providers=default_providers() + [AccessLogProvider()])`,
or extend `default_providers()` in `builder.py`.

## Wiring points (already done)

- `alibi_engine.build_incident_plan(incident, config, context=...)` — caution-only fusion
- `alibi_engine.compile_alert(incident, plan, config, context=...)` — narrative + audit stash
- `llm_service._build_alert_prompt(...)` — advisory context block in the prompt
- `alibi_engine.log_incident_processing(...)` — context provenance in the JSONL audit log

Callers that pass no `context` are unaffected (fully backward compatible).
