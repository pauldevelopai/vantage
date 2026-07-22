"""
One vocabulary for "how far back are we looking?".

Four windows had grown up independently — the dashboard knew 24h/7d/30d, the
patterns API had its own map, People was hardcoded to 168 hours, and the
activity parser spoke 1h/24h/7d/week. Same question, four answers, and no way
to ask for everything. This is the single definition; every page and endpoint
reads from it.

"all" means no cutoff is applied by the query. It does NOT promise data that
was never kept: each store has its own retention (vehicle trails prune at 30
days), so "all time" is honestly "everything still held", which is why
`describe` says so rather than claiming completeness.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

# The four the UI offers, in the order it offers them.
WINDOWS = ("24h", "7d", "30d", "all")

HOURS = {
    "24h": 24.0,
    "7d": 24.0 * 7,
    "30d": 24.0 * 30,
    "all": None,          # None == no cutoff
}

LABELS = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "all": "All time",
}

SHORT = {"24h": "24H", "7d": "7D", "30d": "30D", "all": "All"}

DEFAULT = "24h"

# Older spellings that existed before this module, kept working so no caller
# silently falls back to the default and quietly shows the wrong period.
_ALIASES = {
    "week": "7d", "1w": "7d", "day": "24h", "1d": "24h",
    "month": "30d", "everything": "all", "*": "all", "": DEFAULT,
}


def normalise(window: Optional[str], default: str = DEFAULT) -> str:
    """Any accepted spelling -> one of WINDOWS."""
    w = (window or "").strip().lower()
    w = _ALIASES.get(w, w)
    return w if w in HOURS else default


def window_hours(window: Optional[str], default: str = DEFAULT) -> Optional[float]:
    """Hours to look back, or None for all time.

    Callers MUST handle None — treating it as 0 would show nothing, which is
    the opposite of what "all time" means.
    """
    return HOURS[normalise(window, default)]


def cutoff(window: Optional[str], now: Optional[datetime] = None,
           default: str = DEFAULT) -> Optional[datetime]:
    """The earliest timestamp to include, or None to include everything."""
    hours = window_hours(window, default)
    if hours is None:
        return None
    return (now or datetime.utcnow()) - timedelta(hours=hours)


def within(ts, window: Optional[str], now: Optional[datetime] = None,
           default: str = DEFAULT) -> bool:
    """Is this timestamp inside the window? True for everything when "all"."""
    c = cutoff(window, now, default)
    if c is None:
        return True
    if ts is None:
        return False
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "").strip())
        except ValueError:
            return False
    return ts >= c


def describe(window: Optional[str], default: str = DEFAULT) -> str:
    """How to name this period to a person."""
    return LABELS[normalise(window, default)]


def options() -> list:
    """What the UI should offer, so the client never hardcodes its own list."""
    return [{"key": k, "label": LABELS[k], "short": SHORT[k]} for k in WINDOWS]
