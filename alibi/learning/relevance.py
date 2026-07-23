"""
Relevance learning — the alert panel learns which things are worth YOUR
attention, from the calls you make on it.

Faces already learn (naming one builds that person's gallery). But when the
operator kept seeing the same alert they didn't care about — a known person just
being present, a car that turns out to be fine — nothing remembered that
judgement, so the same low-value alert came back tomorrow. This closes that
loop.

Each time someone marks an alert "not worth flagging" or "confirm", that is
recorded against the SUBJECT (a person's name, a vehicle, or a pattern), and the
ranker reads it back: a subject you keep dismissing sinks; one you confirm rises.
It only ever changes RANK, never hides anything — the adjustment is shown on the
card ("you dismissed this before") and is reversible. It never suppresses a
genuine hotlist/watchlist FLAG; it only reorders how loudly routine things call
for a look.

Append-only and encrypted at rest, like the other stores, so it is an auditable
record of the operator's own judgements — real feedback, never inferred.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

from alibi.encryption import get_encrypted_writer

STORE = Path("alibi/data/alert_feedback.jsonl")

# How hard each net judgement moves a subject. A net dismissal shrinks its
# importance geometrically (one net dismiss → ×0.55, two → ×0.30, floored so a
# subject never fully vanishes — it drops down the list, it is not hidden). A net
# confirmation lifts it. Deliberately gentle: a single stray click barely moves
# anything; a consistent pattern moves it a lot.
_DISMISS_STEP = 0.55
_DISMISS_FLOOR = 0.12
_CONFIRM_STEP = 0.5
_CONFIRM_CEIL = 2.5


def _normalise(subject: Optional[str]) -> str:
    return (subject or "").strip().lower()


class RelevanceStore:
    def __init__(self, path: Path = STORE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._sig: Optional[tuple] = None

    # ── writing ──────────────────────────────────────────────────────────
    def record(self, subject: str, decision: str, kind: Optional[str] = None,
               by: str = "system", note: Optional[str] = None) -> None:
        """Log one judgement. `decision` is 'dismiss' or 'confirm'."""
        subject = _normalise(subject)
        if not subject or decision not in ("dismiss", "confirm"):
            return
        self._crypto.write_line(self.path, {
            "subject": subject, "decision": decision, "kind": kind,
            "by": by, "note": (note or "")[:500],
            "ts": datetime.utcnow().isoformat(),
        })
        self._cache = None                      # force a reload

    # ── reading ──────────────────────────────────────────────────────────
    def _tally(self) -> Dict[str, Dict[str, Any]]:
        """{subject -> {dismiss, confirm, last, by}}, cached on file mtime."""
        try:
            st = self.path.stat()
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = (0, 0)
        if self._cache is not None and self._sig == sig:
            return self._cache

        tally: Dict[str, Dict[str, Any]] = {}
        try:
            for row in self._crypto.read_lines(self.path):
                subj = _normalise(row.get("subject"))
                dec = row.get("decision")
                if not subj or dec not in ("dismiss", "confirm"):
                    continue
                t = tally.setdefault(subj, {"dismiss": 0, "confirm": 0,
                                            "last": None, "by": row.get("by")})
                t[dec] += 1
                t["last"] = row.get("ts")
                t["by"] = row.get("by") or t["by"]
        except Exception as e:
            print(f"[relevance] could not read feedback: {e}", flush=True)

        self._cache, self._sig = tally, sig
        return tally

    def multiplier(self, subject: str) -> float:
        """The learned importance multiplier for a subject (1.0 = untouched)."""
        t = self._tally().get(_normalise(subject))
        if not t:
            return 1.0
        net = t["confirm"] - t["dismiss"]
        if net < 0:
            return max(_DISMISS_FLOOR, _DISMISS_STEP ** (-net))
        if net > 0:
            return min(_CONFIRM_CEIL, 1.0 + _CONFIRM_STEP * net)
        return 1.0

    def adjustments(self) -> Dict[str, float]:
        """{subject -> multiplier} for every subject with a non-neutral history —
        the map the ranker consumes."""
        out: Dict[str, float] = {}
        for subj in self._tally():
            m = self.multiplier(subj)
            if abs(m - 1.0) > 1e-6:
                out[subj] = m
        return out

    def reason_for(self, subject: str) -> Optional[str]:
        """A short, honest note for the card explaining an adjustment."""
        t = self._tally().get(_normalise(subject))
        if not t:
            return None
        net = t["confirm"] - t["dismiss"]
        if net < 0:
            n = t["dismiss"]
            return f"down-ranked — you dismissed this {n}×"
        if net > 0:
            return f"raised — you confirmed this {t['confirm']}×"
        return None

    def summary(self) -> List[Dict[str, Any]]:
        """What the system has learned, for an honest 'learning' surface."""
        rows = []
        for subj, t in self._tally().items():
            m = self.multiplier(subj)
            if abs(m - 1.0) <= 1e-6:
                continue
            rows.append({"subject": subj, "dismissed": t["dismiss"],
                         "confirmed": t["confirm"], "multiplier": round(m, 2),
                         "direction": "down" if m < 1 else "up", "last": t["last"]})
        rows.sort(key=lambda r: str(r.get("last") or ""), reverse=True)
        return rows


_STORE: Optional[RelevanceStore] = None


def get_relevance_store() -> RelevanceStore:
    global _STORE
    if _STORE is None:
        _STORE = RelevanceStore()
    return _STORE
