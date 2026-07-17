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
from typing import Any, Dict, List, Optional

USAGE_FILE = Path("alibi/data/usage.jsonl")

# The Anthropic API does not expose the account's credit balance — there is no
# balance endpoint. So the owner enters it (from console.anthropic.com) and we
# burn it down against our own tracked spend. Honest about what it is: an
# entered figure plus a measured estimate, never a guess presented as a fact.
CREDITS_FILE = Path("alibi/data/api_credits.json")

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
        "credits": credit_status(now=now),
        "note": ("Estimated from Claude token usage at published rates. Apify "
                 "credits and infrastructure are not yet included."),
    }


# ── Credit balance & runout ────────────────────────────────────────────────

def _usage_rows() -> List[Dict[str, Any]]:
    rows = []
    if USAGE_FILE.exists():
        for line in USAGE_FILE.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def set_credits(balance_usd: float, set_by: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Record the account's credit balance as entered by the owner."""
    now = now or datetime.utcnow()
    CREDITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "balance_usd": round(float(balance_usd), 2),
        "set_at": now.isoformat(),
        "set_by": set_by,
    }
    CREDITS_FILE.write_text(json.dumps(data))
    return data


def credit_status(now: Optional[datetime] = None) -> Dict[str, Any]:
    """How much API credit is left and when it runs out, honestly derived:
    the ENTERED balance minus our TRACKED spend since it was entered, projected
    at the measured burn rate (tracked spend over the last 7 days).

    All-null fields when no balance has been entered — the page prompts for it
    rather than inventing a figure."""
    now = now or datetime.utcnow()
    entered = None
    if CREDITS_FILE.exists():
        try:
            entered = json.loads(CREDITS_FILE.read_text())
        except json.JSONDecodeError:
            entered = None
    rows = _usage_rows()

    # Burn rate: tracked spend over the last 7 days, averaged over the days we
    # actually have data for (a service 2 days old shouldn't look 3.5× cheaper).
    week_ago = now - timedelta(days=7)
    week_spend = 0.0
    earliest: Optional[datetime] = None
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if earliest is None or ts < earliest:
            earliest = ts
        if ts >= week_ago:
            week_spend += float(r.get("usd", 0.0))
    if earliest is None:
        observed_days = 0.0
    else:
        observed_days = min(7.0, max((now - earliest).total_seconds() / 86400.0, 1.0 / 24))
    daily_burn = round(week_spend / observed_days, 4) if observed_days > 0 else None

    if not entered:
        return {"balance_usd": None, "set_at": None, "set_by": None,
                "spent_since_usd": None, "remaining_usd": None,
                "daily_burn_usd": daily_burn, "days_left": None, "runout_date": None}

    try:
        set_at = datetime.fromisoformat(entered["set_at"])
    except (ValueError, KeyError, TypeError):
        set_at = now
    spent_since = 0.0
    for r in rows:
        try:
            if datetime.fromisoformat(r["ts"]) >= set_at:
                spent_since += float(r.get("usd", 0.0))
        except (ValueError, KeyError, TypeError):
            continue
    remaining = round(float(entered.get("balance_usd", 0.0)) - spent_since, 4)

    days_left = None
    runout_date = None
    if daily_burn and daily_burn > 0 and remaining > 0:
        days_left = round(remaining / daily_burn, 1)
        runout_date = (now + timedelta(days=days_left)).date().isoformat()
    elif remaining <= 0:
        days_left = 0.0
        runout_date = now.date().isoformat()

    return {
        "balance_usd": entered.get("balance_usd"),
        "set_at": entered.get("set_at"),
        "set_by": entered.get("set_by"),
        "spent_since_usd": round(spent_since, 4),
        "remaining_usd": remaining,
        "daily_burn_usd": daily_burn,
        "days_left": days_left,
        "runout_date": runout_date,
    }
