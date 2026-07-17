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
VISION_MODELS: Dict[str, Dict[str, Any]] = {
    "claude-opus-4-8":  {"label": "Opus 4.8 — most capable", "in_usd": 5.0, "out_usd": 25.0},
    "claude-sonnet-5":  {"label": "Sonnet 5 — near-Opus quality, 40% cheaper", "in_usd": 3.0, "out_usd": 15.0},
    "claude-haiku-4-5": {"label": "Haiku 4.5 — fastest, 5× cheaper than Opus", "in_usd": 1.0, "out_usd": 5.0},
}

DEFAULTS: Dict[str, Any] = {
    "vision_model": "claude-opus-4-8",
    "paid_min_gap_seconds": 60,
    "narrate_vehicles": True,
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
                  narrate_vehicles: bool = None) -> Dict[str, Any]:
    """Update any subset of the config. Validates; raises ValueError on junk."""
    cfg = get_ai_config()
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
