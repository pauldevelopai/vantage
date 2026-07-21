"""
Per-snapshot context: what the AI saw in a frame, and what the owner knows.

Two different things, kept apart on purpose and never merged:
  * `description` — the vision model's account of THIS frame. Generated on
    demand (or carried over from the event the frame belongs to). It is a
    machine's reading of a picture, nothing more.
  * `note` — the owner's own words about the frame. A human statement, with
    their name and the time attached.

Small JSON store keyed by frame_id; frames are already stored as
alibi/data/frames/<frame_id>.jpg, so this just hangs context off them.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

NOTES_FILE = Path("alibi/data/frame_notes.json")

# The basic-CV fallback writes pixel-statistics strings when NO vision model
# ran. They describe nothing — never store or return them as a description.
GENERIC_DESCRIPTIONS = {
    "static scene, very low activity",
    "calm scene with minimal movement",
    "moderate activity detected",
    "high activity or complex scene detected",
}


def is_real_description(text: Optional[str]) -> bool:
    """A description only counts if a model actually looked at the picture."""
    t = (text or "").strip()
    return bool(t) and t.lower() not in GENERIC_DESCRIPTIONS


def _load() -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(NOTES_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(json.dumps(data))


def get(frame_id: str) -> Dict[str, Any]:
    return _load().get(str(frame_id)) or {}


def set_description(frame_id: str, description: str,
                    method: Optional[str] = None,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """Store the model's reading of this frame. Refuses the basic-CV fallback."""
    if not is_real_description(description):
        return get(frame_id)
    data = _load()
    row = data.get(str(frame_id)) or {}
    row["description"] = description.strip()[:2000]
    row["described_at"] = (now or datetime.utcnow()).isoformat()
    if method:
        row["method"] = method
    data[str(frame_id)] = row
    _save(data)
    return row


def set_note(frame_id: str, note: str, set_by: str,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    """The owner's own words about this frame. Empty note clears it."""
    data = _load()
    row = data.get(str(frame_id)) or {}
    text = (note or "").strip()[:2000]
    if text:
        row["note"] = text
        row["note_by"] = set_by
        row["note_at"] = (now or datetime.utcnow()).isoformat()
    else:
        row.pop("note", None)
        row.pop("note_by", None)
        row.pop("note_at", None)
    data[str(frame_id)] = row
    _save(data)
    return row
