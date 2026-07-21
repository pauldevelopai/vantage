"""
What the cameras got wrong, and what to do about it.

Every time someone answers "yes, that's a face" or "no, it isn't", that is a
labelled example: a detector score, and the truth about it. Enough of them and
we no longer have to guess where the line goes — we can put it where THIS
site's answers say it belongs. A camera looking down a dark driveway and one
watching a bright gate do not deserve the same threshold, and nobody should
have to tune them by hand.

This is not model retraining. SCRFD's weights never change; fine-tuning a
detector needs thousands of labelled boxes and a GPU, and doing it from a
handful of clicks would overfit to those clicks. What changes is the decision
we make with the score it gives us — which is the part that was actually wrong
when a real face scoring 0.481 was thrown away by a threshold of 0.5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

FEEDBACK_FILE = Path("alibi/data/face_feedback.jsonl")

# Never let learning wander outside this band, however one-sided the answers.
# Below the floor we would be enrolling texture; above the ceiling we are back
# to discarding real faces, which is the mistake that started this.
FLOOR = 0.30
CEILING = 0.60

# How much evidence before we move off the default at all, and how many of
# each answer. One person clicking "yes" three times is not a calibration.
MIN_DECISIONS = 8
MIN_PER_CLASS = 3


@dataclass
class Decision:
    """One human answer about one detection."""
    ts: str
    camera_id: str
    score: float           # what the detector said
    accepted: bool         # what the person said
    source: str = "recover"
    note: Optional[str] = None


def record(camera_id: str, score: float, accepted: bool,
           source: str = "recover", note: str | None = None,
           path: Path | None = None, now: datetime | None = None) -> Decision:
    """Append one answer. Never raises — losing a correction must not break
    the click that produced it."""
    d = Decision(ts=(now or datetime.utcnow()).isoformat(),
                 camera_id=camera_id or "", score=round(float(score), 4),
                 accepted=bool(accepted), source=source, note=note)
    p = path or FEEDBACK_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(asdict(d)) + "\n")
    except Exception as e:  # pragma: no cover
        print(f"[face-feedback] could not record decision: {e}")
    return d


def load(camera_id: str | None = None, path: Path | None = None) -> List[Decision]:
    """Every answer, optionally for one camera."""
    p = path or FEEDBACK_FILE
    out: List[Decision] = []
    try:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                d = Decision(ts=row.get("ts", ""), camera_id=row.get("camera_id", ""),
                             score=float(row.get("score", 0.0)),
                             accepted=bool(row.get("accepted")),
                             source=row.get("source", ""), note=row.get("note"))
                if camera_id is None or d.camera_id == camera_id:
                    out.append(d)
    except FileNotFoundError:
        return []
    except Exception as e:  # pragma: no cover
        print(f"[face-feedback] could not read decisions: {e}")
    return out


def best_split(decisions: List[Decision], default: float) -> float:
    """The threshold this site's own answers argue for.

    Sweep every line between observed scores and keep the one that gets the
    most answers right: accepted faces at or above it, rejected ones below.
    Ties go to the LOWER threshold — the failure that brought us here was
    discarding a real face, and a false positive costs a person one click
    while a missed face costs them a person they wanted recognised.
    """
    yes = [d.score for d in decisions if d.accepted]
    no = [d.score for d in decisions if not d.accepted]
    if len(decisions) < MIN_DECISIONS or len(yes) < MIN_PER_CLASS or len(no) < MIN_PER_CLASS:
        return default

    candidates = sorted({round(s, 4) for s in ([d.score for d in decisions] + [FLOOR, CEILING])})
    best_t, best_correct = default, -1
    for t in candidates:
        t = min(max(t, FLOOR), CEILING)
        correct = sum(1 for s in yes if s >= t) + sum(1 for s in no if s < t)
        if correct > best_correct:            # strictly greater => lowest wins ties
            best_t, best_correct = t, correct
    return round(min(max(best_t, FLOOR), CEILING), 4)


def learned_threshold(camera_id: str, default: float,
                      path: Path | None = None) -> float:
    """What this camera's threshold should be, given what it's been told.

    Falls back to `default` until there is enough evidence, so a new
    deployment behaves exactly as it does today.
    """
    return best_split(load(camera_id, path=path), default)


def summary(camera_id: str | None = None, path: Path | None = None) -> dict:
    """What the system has learned so far, in a form worth showing a person."""
    ds = load(camera_id, path=path)
    yes = [d for d in ds if d.accepted]
    no = [d for d in ds if not d.accepted]
    return {
        "decisions": len(ds),
        "confirmed": len(yes),
        "rejected": len(no),
        "needed_before_learning": max(0, MIN_DECISIONS - len(ds)),
        "lowest_confirmed": round(min((d.score for d in yes), default=0.0), 3) or None,
        "highest_rejected": round(max((d.score for d in no), default=0.0), 3) or None,
    }
