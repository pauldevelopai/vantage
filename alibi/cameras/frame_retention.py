"""
Which pictures are worth keeping, and which are just weather.

Nothing swept the frame store, so it grew forever: 23,195 files and 1.7GB in
five days on the live box — about 124GB a year against 50GB free. It would
have filled the disk around Christmas.

Measured, 89% of those frames are referenced by nothing at all. They are motion
uploads where the detector then found no person and no vehicle: an empty
driveway at 3am, a branch moving. The remaining 11% are the evidence behind
real events, and a small core of those is irreplaceable — the shot you named
someone from, the one you wrote a note on, the one behind a confirmed incident.

So three tiers, most protective first:

  keep for good  the frame is someone's identity, someone's words, or proof of
                 something that happened. Deleting it destroys the only copy of
                 an answer the system has already given.
  keep a while   a real detection, worth reviewing for a season, not for ever.
  sweep soon     nothing was found in it and nobody has looked at it.

The rule that matters: a frame referenced by ANY evidence is never deleted by
this module, whatever its age. A broken image on the People page is not a tidy
disk — it is the system forgetting something it told you it knew.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple

FRAMES_DIR = Path("alibi/data/frames")

# Ordinary detections: long enough to review a season of activity.
KEEP_REFERENCED_DAYS = 90
# Frames nothing was found in: long enough to notice and look, no longer.
KEEP_UNREFERENCED_DAYS = 7

_FRAME_RE = re.compile(r"frames/([0-9A-Za-z_-]{6,})")


def frame_ids_in(text: Optional[str]) -> Set[str]:
    """Every frame id mentioned in a url or blob of json."""
    if not text:
        return set()
    return {m.split(".")[0] for m in _FRAME_RE.findall(text)}


@dataclass
class Value:
    """Why a frame is worth keeping — the reasons, not just a verdict."""
    forever: Dict[str, str] = field(default_factory=dict)   # frame_id -> reason
    referenced: Dict[str, str] = field(default_factory=dict)

    def note(self, frame_id: str, reason: str, forever: bool) -> None:
        if not frame_id:
            return
        if forever:
            self.forever.setdefault(frame_id, reason)
            self.referenced.pop(frame_id, None)
        elif frame_id not in self.forever:
            self.referenced.setdefault(frame_id, reason)

    @property
    def all_kept(self) -> Set[str]:
        return set(self.forever) | set(self.referenced)


@dataclass
class SweepPlan:
    """What a sweep WOULD do. Nothing is deleted to produce this."""
    delete: list = field(default_factory=list)
    keep_forever: int = 0
    keep_referenced: int = 0
    keep_recent: int = 0
    bytes_freed: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)
    aborted: Optional[str] = None

    @property
    def deleting(self) -> int:
        return len(self.delete)


def plan_sweep(
    frames: Iterable[Tuple[str, datetime, int]],
    value: Value,
    now: Optional[datetime] = None,
    keep_referenced_days: int = KEEP_REFERENCED_DAYS,
    keep_unreferenced_days: int = KEEP_UNREFERENCED_DAYS,
) -> SweepPlan:
    """Decide the fate of each frame. Pure — `frames` is (id, mtime, size).

    Nothing in `value.forever` is ever proposed for deletion, at any age.
    """
    now = now or datetime.now()
    ref_cutoff = now - timedelta(days=keep_referenced_days)
    unref_cutoff = now - timedelta(days=keep_unreferenced_days)

    plan = SweepPlan()
    for frame_id, mtime, size in frames:
        if frame_id in value.forever:
            plan.keep_forever += 1
            reason = value.forever[frame_id]
            plan.reasons[reason] = plan.reasons.get(reason, 0) + 1
            continue

        referenced = frame_id in value.referenced
        cutoff = ref_cutoff if referenced else unref_cutoff
        if mtime >= cutoff:
            if referenced:
                plan.keep_referenced += 1
            else:
                plan.keep_recent += 1
            continue

        plan.delete.append(frame_id)
        plan.bytes_freed += max(0, size)
    return plan


def collect_value(data_dir: Path = Path("alibi/data")) -> Value:
    """Read every store that can vouch for a frame.

    Raises if a source cannot be read. The caller MUST treat that as a reason
    not to sweep: a store we failed to open is a store whose frames we would
    wrongly consider orphans.
    """
    from alibi.encryption import get_encrypted_writer

    crypto = get_encrypted_writer()
    value = Value()

    # Someone's identity — the shot an enrolled person was named from.
    for record in crypto.read_lines(data_dir / "watchlist.jsonl"):
        if record.get("source_ref") == "REMOVED":
            continue
        label = record.get("label") or "someone"
        for fid in frame_ids_in(json.dumps(record.get("metadata") or {})):
            value.note(fid, f"how you recognise {label}", forever=True)

    # Faces: named ones are identity, unknown ones are still real faces.
    for record in crypto.read_lines(data_dir / "face_sightings.jsonl"):
        for fid in frame_ids_in(record.get("image_path")):
            if record.get("matched_person_id"):
                value.note(fid, "a named person's face", forever=True)
            else:
                value.note(fid, "a face we may yet name", forever=True)

    # Your own words, and any account a vision model has already written.
    notes_file = data_dir / "frame_notes.json"
    if notes_file.exists():
        for fid, row in (json.loads(notes_file.read_text()) or {}).items():
            if (row or {}).get("note"):
                value.note(fid, "you wrote a note on it", forever=True)
            elif (row or {}).get("description"):
                value.note(fid, "already described by AI", forever=True)

    # Events: plates, alerts and confirmed incidents are evidence for good;
    # ordinary detections are worth a season.
    confirmed = _confirmed_event_ids(crypto, data_dir)
    for record in crypto.read_lines(data_dir / "events.jsonl"):
        ids = frame_ids_in(record.get("snapshot_url"))
        if not ids:
            continue
        intel = ((record.get("metadata") or {}).get("intel") or {})
        forever, reason = False, "a real detection"
        if record.get("event_id") in confirmed:
            forever, reason = True, "evidence for a confirmed incident"
        elif intel.get("plates"):
            forever, reason = True, "a readable number plate"
        elif (record.get("metadata") or {}).get("watchlist_hit"):
            forever, reason = True, "a watchlist match"
        elif int(record.get("severity") or 0) >= 4:
            forever, reason = True, "a high-severity event"
        for fid in ids:
            value.note(fid, reason, forever=forever)

    return value


def _confirmed_event_ids(crypto, data_dir: Path) -> Set[str]:
    """Events belonging to an incident a human confirmed or escalated."""
    out: Set[str] = set()
    path = data_dir / "incidents.jsonl"
    if not path.exists():
        return out
    latest: Dict[str, dict] = {}
    for record in crypto.read_lines(path):
        iid = record.get("incident_id")
        if iid:
            latest[iid] = record
    for record in latest.values():
        if record.get("status") in ("confirmed", "escalated"):
            out.update(record.get("event_ids") or [])
    return out


def scan_frames(frames_dir: Path = FRAMES_DIR):
    """(frame_id, mtime, size) for every stored frame."""
    if not frames_dir.exists():
        return []
    out = []
    for p in frames_dir.glob("*.jpg"):
        try:
            st = p.stat()
        except OSError:
            continue
        out.append((p.stem, datetime.fromtimestamp(st.st_mtime), st.st_size))
    return out


def sweep(dry_run: bool = True, frames_dir: Path = FRAMES_DIR,
          data_dir: Path = Path("alibi/data"), **policy) -> SweepPlan:
    """Plan a sweep and, unless dry_run, carry it out.

    If the evidence stores cannot be read we abort without deleting anything.
    Sweeping blind would treat every frame as an orphan and delete the lot.
    """
    try:
        value = collect_value(data_dir)
    except Exception as e:
        plan = SweepPlan()
        plan.aborted = f"could not read the evidence stores, so nothing was swept: {e}"
        print(f"[frame-retention] ABORTED — {plan.aborted}")
        return plan

    plan = plan_sweep(scan_frames(frames_dir), value, **policy)
    if dry_run or not plan.delete:
        return plan

    freed = 0
    for frame_id in plan.delete:
        p = frames_dir / f"{frame_id}.jpg"
        try:
            freed += p.stat().st_size
            p.unlink()
        except OSError:
            continue
    plan.bytes_freed = freed
    # flush: journald block-buffers stdout, and a deletion nobody can see in
    # the log is a deletion nobody can question.
    print(f"[frame-retention] swept {plan.deleting} frames, freed "
          f"{freed / 1048576:.0f}MB; kept {plan.keep_forever} for good", flush=True)
    return plan
