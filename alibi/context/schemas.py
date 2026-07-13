"""
External-context schemas for the incident advisor.

Context is *advisory input to the human-facing narrative*, plus a caution-only
signal path. It NEVER lowers severity, never auto-dispatches, and never downgrades
a human-review requirement. It can only:
  - be surfaced to the operator (narrative / audit), and
  - ADD a risk flag or FORCE human review (caution-only).

Every item is three-state so "we couldn't check the source" is never rendered as
"all clear":
  PRESENT     - the source was reached and has relevant data
  ABSENT      - the source was reached and confirms there is nothing relevant
  UNAVAILABLE - the source could not be checked (down, not configured, errored)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Availability(str, Enum):
    """Three-state availability for a context item."""
    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


@dataclass
class ContextItem:
    """A single piece of non-video context attached to an incident."""
    provider: str                       # machine name, e.g. "activity_baseline"
    label: str                          # short human heading, e.g. "Activity baseline"
    availability: Availability
    summary: str = ""                   # neutral, operator-readable (guarded for language)
    source: str = ""                    # provenance, e.g. "learned baseline (7d)"
    as_of: Optional[datetime] = None    # when the underlying data is valid
    caution_signals: List[str] = field(default_factory=list)  # -> plan.action_risk_flags
    elevate_review: bool = False        # caution-only: force requires_human_approval=True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def staleness_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        if self.as_of is None:
            return None
        now = now or datetime.utcnow()
        return max(0.0, (now - self.as_of).total_seconds())

    def to_audit_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["availability"] = self.availability.value
        d["as_of"] = self.as_of.isoformat() if self.as_of else None
        return d


@dataclass
class ContextBundle:
    """The full set of context gathered for one incident."""
    items: List[ContextItem] = field(default_factory=list)

    @property
    def present_items(self) -> List[ContextItem]:
        return [i for i in self.items if i.availability == Availability.PRESENT]

    @property
    def unavailable_items(self) -> List[ContextItem]:
        return [i for i in self.items if i.availability == Availability.UNAVAILABLE]

    @property
    def caution_flags(self) -> List[str]:
        """De-duplicated risk flags contributed by present context items."""
        flags: List[str] = []
        for item in self.present_items:
            for sig in item.caution_signals:
                if sig not in flags:
                    flags.append(sig)
        return flags

    @property
    def requires_review(self) -> bool:
        """True if any present item asks to force human review (caution-only)."""
        return any(i.elevate_review for i in self.present_items)

    def is_empty(self) -> bool:
        return len(self.items) == 0

    def render_for_prompt(self) -> str:
        """
        Render a neutral context block for the LLM prompt.

        UNAVAILABLE items are included on purpose so the model surfaces the
        uncertainty rather than assuming the absence of a signal is reassuring.
        """
        if not self.items:
            return ""

        lines = ["FACILITY / AREA CONTEXT (advisory - do NOT attribute to the detected individual):"]
        now = datetime.utcnow()
        for item in self.items:
            if item.availability == Availability.UNAVAILABLE:
                lines.append(f"  - [{item.label}] SOURCE UNAVAILABLE - could not be verified; do not assume 'all clear'.")
                continue
            if item.availability == Availability.ABSENT:
                lines.append(f"  - [{item.label}] Checked, nothing relevant on record ({item.source}).")
                continue
            # PRESENT
            stale = ""
            secs = item.staleness_seconds(now)
            if secs is not None and secs > 3600:
                stale = f" (as of {int(secs // 3600)}h ago)"
            lines.append(f"  - [{item.label}] {item.summary} — source: {item.source}{stale}")
        return "\n".join(lines)

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "items": [i.to_audit_dict() for i in self.items],
            "caution_flags": self.caution_flags,
            "requires_review": self.requires_review,
        }
