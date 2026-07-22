"""
"That isn't them."

Naming a face is reversible and has to be, because the cost of a wrong name is
carried by whoever was misnamed. On 2026-07-22 eight candidate faces were
confirmed as one person in a single action; several were other people
entirely, and the archive then held their pictures labelled with his name.

A rejection does three things, and the third is the point:

  * the attribution is removed from the stored sighting;
  * the view is dropped from that person's gallery, so it stops dragging
    matches towards the wrong face; and
  * it is REMEMBERED, so the same face is never suggested for that person
    again. Undoing a mistake that gets re-offered next week is not undoing it.

Rejections are per (person, face). Saying a face is not Paul says nothing
about who it is, and the system must not infer one — an unattributed face goes
back to being an unknown person, which is the honest state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set

REJECTIONS_FILE = Path("alibi/data/face_rejections.json")


def _load(path: Optional[Path] = None) -> Dict[str, list]:
    p = path or REJECTIONS_FILE
    try:
        return json.loads(p.read_text()) or {}
    except (FileNotFoundError, ValueError):
        return {}
    except Exception as e:  # pragma: no cover
        print(f"[rejections] unreadable, treating as empty: {e}")
        return {}


def record(person_id: str, sighting_id: str, by: str = "",
           path: Optional[Path] = None, now: Optional[datetime] = None) -> None:
    """Remember that this face is NOT this person."""
    if not person_id or not sighting_id:
        return
    p = path or REJECTIONS_FILE
    data = _load(p)
    rows = data.setdefault(person_id, [])
    if any(r.get("sighting_id") == sighting_id for r in rows):
        return
    rows.append({"sighting_id": sighting_id, "by": by,
                 "ts": (now or datetime.utcnow()).isoformat()})
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except Exception as e:  # pragma: no cover
        print(f"[rejections] could not save: {e}")


def rejected_for(person_id: str, path: Optional[Path] = None) -> Set[str]:
    """Face sightings this person has been ruled out of."""
    return {r.get("sighting_id") for r in _load(path).get(person_id, [])
            if r.get("sighting_id")}


def all_rejections(path: Optional[Path] = None) -> Dict[str, Set[str]]:
    return {pid: {r.get("sighting_id") for r in rows if r.get("sighting_id")}
            for pid, rows in _load(path).items()}


def is_rejected(person_id: str, sighting_id: str,
                path: Optional[Path] = None) -> bool:
    return sighting_id in rejected_for(person_id, path)
