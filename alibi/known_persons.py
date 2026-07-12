"""
Known Persons Store

People tagged from the mobile camera flow as trusted / neutral / watch, with an
optional reference snapshot. Backed by a JSON file, loaded into memory.

Reconstructed to match the API used by mobile_camera_enhanced.py (tag/list/get/
update/remove person endpoints) and continuous_learning.py (authorized-person
prompt context). Real persistence — no placeholder data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional


@dataclass
class KnownPerson:
    """A person tagged as known, with a trust level."""
    person_id: str
    name: str
    role: str                       # resident | visitor | staff | family | security | delivery | other
    description: str
    added_by: str
    added_at: str                   # ISO timestamp
    reference_image_path: Optional[str] = None
    notes: str = ""
    is_authorized: bool = True
    trust_level: str = "neutral"    # trusted | neutral | watch

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KnownPersonsStore:
    """
    In-memory index of KnownPerson records with JSON persistence.

    Storage: alibi/data/known_persons.json (a JSON array of person dicts).
    """

    def __init__(self, store_file: str = "alibi/data/known_persons.json"):
        self.store_file = Path(store_file)
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self._persons: Dict[str, KnownPerson] = {}
        self._load()

    def _load(self) -> None:
        if not self.store_file.exists():
            return
        try:
            raw = self.store_file.read_text().strip() or "[]"
            for d in json.loads(raw):
                fields = {k: d.get(k) for k in KnownPerson.__annotations__ if k in d}
                p = KnownPerson(**fields)
                self._persons[p.person_id] = p
        except Exception as e:
            print(f"[KnownPersonsStore] Error loading {self.store_file}: {e}")

    def _save(self) -> None:
        try:
            self.store_file.write_text(
                json.dumps([asdict(p) for p in self._persons.values()], indent=2)
            )
        except Exception as e:
            print(f"[KnownPersonsStore] Error saving {self.store_file}: {e}")

    def add_person(self, person: KnownPerson) -> None:
        self._persons[person.person_id] = person
        self._save()

    def get_all_persons(self) -> List[KnownPerson]:
        return list(self._persons.values())

    def get_person(self, person_id: str) -> Optional[KnownPerson]:
        return self._persons.get(person_id)

    def get_authorized_persons(self) -> List[KnownPerson]:
        return [p for p in self._persons.values() if p.is_authorized]

    def update_person(self, person_id: str, updates: Dict[str, Any]) -> bool:
        person = self._persons.get(person_id)
        if not person:
            return False
        for key, value in updates.items():
            if hasattr(person, key):
                setattr(person, key, value)
        self._save()
        return True

    def remove_person(self, person_id: str) -> bool:
        if person_id not in self._persons:
            return False
        del self._persons[person_id]
        self._save()
        return True


_store_instance: Optional[KnownPersonsStore] = None


def get_known_persons_store() -> KnownPersonsStore:
    """Get or create the global known-persons store."""
    global _store_instance
    if _store_instance is None:
        _store_instance = KnownPersonsStore()
    return _store_instance
