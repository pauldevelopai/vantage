"""
Owner-tunable AI spend controls, set from the Costs page.

Three levers, each a direct cost dial:
  * vision_model          — which Claude model narrates frames (price tiers below)
  * paid_min_gap_seconds  — at most one PAID vision call per camera per this many
                            seconds (the free local detector still runs on every
                            frame; only the narration is throttled)
  * narrate_vehicles      — whether plain vehicle frames earn a paid call at all
                            (people and hotlist/watchlist hits always do)

Stored as a small JSON file so a restart keeps the owner's choice. Reads are
cheap and never raise — a broken file falls back to defaults.
"""

import json
from pathlib import Path
from typing import Any, Dict

CONFIG_FILE = Path("alibi/data/ai_config.json")

# Allowed vision models with USD per 1M tokens (input, output) — shown on the
# Costs page so the choice is an informed one. Keep in sync with cost_tracker.
# `local: True` models run offline (Ollama on the box/PC) at $0 — data stays
# on-site AND, because they cost nothing, they describe EVERY frame (the paid
# throttle is bypassed for them).
VISION_MODELS: Dict[str, Dict[str, Any]] = {
    "claude-opus-4-8":  {"label": "Opus 4.8 — most capable", "in_usd": 5.0, "out_usd": 25.0},
    "claude-sonnet-5":  {"label": "Sonnet 5 — near-Opus quality, 40% cheaper", "in_usd": 3.0, "out_usd": 15.0},
    "claude-haiku-4-5": {"label": "Haiku 4.5 — fastest, 5× cheaper than Opus", "in_usd": 1.0, "out_usd": 5.0},
    "ollama:llama3.2-vision": {"label": "Offline (local Ollama) — free, describes every frame, data stays on-site",
                               "in_usd": 0.0, "out_usd": 0.0, "local": True},
}


def is_local_vision(model: str) -> bool:
    """True when the vision model runs offline for free (Ollama)."""
    spec = VISION_MODELS.get(model or "")
    return bool(spec and spec.get("local"))

DEFAULTS: Dict[str, Any] = {
    "vision_model": "claude-opus-4-8",
    "paid_min_gap_seconds": 60,
    "narrate_vehicles": True,
    "narrate_people": True,
    "schedule": "always",          # always | after_hours | night
    "daily_budget_usd": 0.0,       # 0 = no daily cap
}

_GAP_CHOICES = (8, 30, 60, 120, 300)


def get_ai_config() -> Dict[str, Any]:
    """Current config with defaults filled in. Never raises."""
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.exists():
            stored = json.loads(CONFIG_FILE.read_text())
            if isinstance(stored, dict):
                cfg.update({k: stored[k] for k in DEFAULTS if k in stored})
    except (json.JSONDecodeError, OSError):
        pass
    # Re-validate on read so a hand-edited file can't select an unknown model.
    if cfg["vision_model"] not in VISION_MODELS:
        cfg["vision_model"] = DEFAULTS["vision_model"]
    return cfg


def set_ai_config(vision_model: str = None, paid_min_gap_seconds: int = None,
                  narrate_vehicles: bool = None, narrate_people: bool = None,
                  schedule: str = None, daily_budget_usd: float = None) -> Dict[str, Any]:
    """Update any subset of the config. Validates; raises ValueError on junk."""
    cfg = get_ai_config()
    if narrate_people is not None:
        cfg["narrate_people"] = bool(narrate_people)
    if schedule is not None:
        if schedule not in SCHEDULES:
            raise ValueError(f"schedule must be one of {SCHEDULES}")
        cfg["schedule"] = schedule
    if daily_budget_usd is not None:
        b = float(daily_budget_usd)
        if b < 0:
            raise ValueError("daily_budget_usd must be >= 0")
        cfg["daily_budget_usd"] = round(b, 2)
    if vision_model is not None:
        if vision_model not in VISION_MODELS:
            raise ValueError(f"unknown vision model: {vision_model}")
        cfg["vision_model"] = vision_model
    if paid_min_gap_seconds is not None:
        gap = int(paid_min_gap_seconds)
        if gap not in _GAP_CHOICES:
            raise ValueError(f"paid_min_gap_seconds must be one of {_GAP_CHOICES}")
        cfg["paid_min_gap_seconds"] = gap
    if narrate_vehicles is not None:
        cfg["narrate_vehicles"] = bool(narrate_vehicles)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg))
    return cfg


# ── When narration is allowed (the trigger policy) ─────────────────────────

SCHEDULES = ("always", "after_hours", "night")
NIGHT_START_MIN = 22 * 60      # fallback night window, site-local
NIGHT_END_MIN = 6 * 60


def narration_allowed(cfg: Dict[str, Any], has_person: bool, has_vehicle: bool,
                      flagged: bool, local_minutes: int,
                      todays_spend_usd: float,
                      normal_hours: Dict[str, Any] = None) -> bool:
    """Should this frame earn a PAID narration? Pure — the whole trigger
    policy in one testable place.

    Hotlist/watchlist hits ALWAYS narrate: a flagged frame is never a place to
    save money. Everything else respects the owner's dials:
      * subject toggles  — narrate people / narrate vehicles
      * schedule         — always | after_hours (outside the site's normal
                           hours; falls back to the night window if hours are
                           unset) | night (22:00–06:00 site-local)
      * daily budget     — hard stop once today's vision spend reaches it
    """
    if flagged:
        return True
    if has_person and not cfg.get("narrate_people", True):
        has_person = False
    if has_vehicle and not cfg.get("narrate_vehicles", True):
        has_vehicle = False
    if not (has_person or has_vehicle):
        return False

    # A free/local model has no cost, so there's nothing to save by throttling —
    # describe every worth-narrating frame (this is what brings "tell me what's
    # in every shot" back at $0). The paid schedule/budget/gap only apply to
    # models that actually cost money.
    if is_local_vision(cfg.get("vision_model", "")):
        return True

    budget = float(cfg.get("daily_budget_usd") or 0)
    if budget > 0 and todays_spend_usd >= budget:
        return False

    schedule = cfg.get("schedule", "always")
    if schedule == "always":
        return True
    start, end = NIGHT_START_MIN, NIGHT_END_MIN
    if schedule == "after_hours" and normal_hours:
        try:
            oh, om = str(normal_hours.get("open", "")).split(":")
            ch, cm = str(normal_hours.get("close", "")).split(":")
            # narrate OUTSIDE normal hours: night window = close -> open
            start, end = int(ch) * 60 + int(cm), int(oh) * 60 + int(om)
        except (ValueError, AttributeError):
            pass
    if start < end:                      # window within one day
        return start <= local_minutes < end
    return local_minutes >= start or local_minutes < end   # overnight window
