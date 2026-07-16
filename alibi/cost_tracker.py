"""
Service usage & cost tracking.

Every Claude call records its token usage here; the cost page aggregates it into
an estimate of what the service is spending. Honest and self-hosted: we log the
usage the API reports and price it with the published per-model rates — no
guessing, and it says plainly what isn't captured yet (e.g. Apify credits).

`cost_usd` (the pricing maths) is pure and unit-tested; `record` / `summary` are
thin JSONL wrappers.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

USAGE_FILE = Path("alibi/data/usage.jsonl")

# USD per 1M tokens: (input, output). Keep in sync with the model table.
PRICING: Dict[str, tuple] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}
_DEFAULT_RATE = (5.0, 25.0)     # unknown model -> price as Opus-tier (don't undercount)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD for a call. Pure."""
    in_rate, out_rate = PRICING.get(model or "", _DEFAULT_RATE)
    return round((input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate, 6)


def record(service: str, model: str, input_tokens: int, output_tokens: int,
           now: Optional[datetime] = None) -> None:
    """Append one usage record. Never raises (billing telemetry must not break a
    request)."""
    try:
        now = now or datetime.utcnow()
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": now.isoformat(),
            "service": service,
            "model": model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "usd": cost_usd(model, input_tokens or 0, output_tokens or 0),
        }
        with open(USAGE_FILE, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def record_from_response(service: str, model: str, response, now: Optional[datetime] = None) -> None:
    """Extract usage from an Anthropic response object and record it."""
    usage = getattr(response, "usage", None)
    record(service, model,
           getattr(usage, "input_tokens", 0) if usage else 0,
           getattr(usage, "output_tokens", 0) if usage else 0,
           now=now)


def summary(window_days: int = 30, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Aggregate usage over the window: total, per-service, per-day."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=window_days)
    by_service: Dict[str, Dict[str, float]] = {}
    by_day: Dict[str, Dict[str, float]] = {}
    total = 0.0

    if USAGE_FILE.exists():
        for line in USAGE_FILE.read_text().splitlines():
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(r["ts"])
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
            if ts < cutoff:
                continue
            svc = r.get("service", "other")
            usd = float(r.get("usd", 0.0))
            total += usd
            s = by_service.setdefault(svc, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})
            s["calls"] += 1
            s["input_tokens"] += int(r.get("input_tokens", 0))
            s["output_tokens"] += int(r.get("output_tokens", 0))
            s["usd"] = round(s["usd"] + usd, 6)
            day = ts.date().isoformat()
            d = by_day.setdefault(day, {"usd": 0.0, "calls": 0})
            d["usd"] = round(d["usd"] + usd, 6)
            d["calls"] += 1

    return {
        "currency": "USD",
        "window_days": window_days,
        "total_usd": round(total, 4),
        "by_service": by_service,
        "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
        "note": ("Estimated from Claude token usage at published rates. Apify "
                 "credits and infrastructure are not yet included."),
    }
