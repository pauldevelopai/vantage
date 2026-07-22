"""
Watchlist Store

JSONL storage for City Police wanted list.
Stores person_id, label, embeddings, and metadata.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict

from alibi.encryption import get_encrypted_writer


@dataclass
class WatchlistEntry:
    """Entry in the watchlist"""
    person_id: str
    label: str  # Name/alias (for operator reference only)
    embedding: List[float]  # Face embedding vector
    added_ts: str  # ISO timestamp
    source_ref: str  # Reference to source document/case
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        return {
            "person_id": self.person_id,
            "label": self.label,
            "embedding": self.embedding,
            "added_ts": self.added_ts,
            "source_ref": self.source_ref,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WatchlistEntry':
        """Create from dictionary"""
        return cls(
            person_id=data["person_id"],
            label=data["label"],
            embedding=data["embedding"],
            added_ts=data["added_ts"],
            source_ref=data["source_ref"],
            metadata=data.get("metadata", {})
        )
    
    def get_embedding_array(self) -> np.ndarray:
        """Get embedding as numpy array"""
        return np.array(self.embedding, dtype=np.float32)


class WatchlistStore:
    """
    JSONL-based storage for watchlist entries.
    
    Append-only for audit trail.
    """
    
    def __init__(self, storage_path: str = "alibi/data/watchlist.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()

        # Create file if it doesn't exist
        if not self.storage_path.exists():
            self.storage_path.touch()
            print(f"[WatchlistStore] Created new watchlist file: {self.storage_path}")
    
    def add_entry(self, entry: WatchlistEntry) -> None:
        """
        Add entry to watchlist (encrypted at rest).

        Args:
            entry: WatchlistEntry to add
        """
        self._crypto.write_line(self.storage_path, entry.to_dict())
        print(f"[WatchlistStore] Added entry: {entry.person_id} - {entry.label}")
    
    def load_all(self) -> List[WatchlistEntry]:
        """
        Load all watchlist entries.

        Returns:
            List of WatchlistEntry objects
        """
        entries = []

        if not self.storage_path.exists():
            return entries

        for data in self._crypto.read_lines(self.storage_path):
            try:
                entries.append(WatchlistEntry.from_dict(data))
            except Exception as e:
                print(f"[WatchlistStore] Error loading entry: {e}")

        return entries
    
    def get_by_person_id(self, person_id: str) -> Optional[WatchlistEntry]:
        """
        Get entry by person_id (returns most recent if multiple).
        
        Args:
            person_id: Person ID to search for
            
        Returns:
            WatchlistEntry or None
        """
        entries = self.load_all()
        
        # Return most recent entry with matching person_id
        for entry in reversed(entries):
            if entry.person_id == person_id:
                return entry
        
        return None
    
    def _get_active_entries(self) -> Dict[str, 'WatchlistEntry']:
        """
        Get most recent entry per person_id, excluding removed entries.

        Removed entries have source_ref == "REMOVED" or empty embedding.
        """
        entries = self.load_all()
        latest = {}
        for entry in entries:
            latest[entry.person_id] = entry
        # Filter out removed entries
        return {
            pid: entry for pid, entry in latest.items()
            if entry.source_ref != "REMOVED" and len(entry.embedding) > 0
        }

    def get_galleries(self) -> Dict[str, np.ndarray]:
        """Every confirmed face we hold for each person, stacked (N, D).

        A person is not one photograph. Someone enrolled head-on at the gate
        looks very different looking down at a phone in the driveway, and a
        single template will miss them there. Each time someone confirms a
        face, that view joins the person's gallery, and matching compares
        against all of them — so the system genuinely gets better at
        recognising the people it has been corrected about.

        The LABEL still comes from the latest entry (renaming stays last-wins),
        and a person whose latest entry is REMOVED is gone entirely.
        """
        entries = self.load_all()
        latest = {}
        for entry in entries:
            latest[entry.person_id] = entry

        from alibi.watchlist import rejections
        rejected = rejections.all_rejections()

        galleries: Dict[str, list] = {}
        for entry in entries:
            head = latest.get(entry.person_id)
            if head is None or head.source_ref == "REMOVED":
                continue                       # deliberately removed person
            if entry.source_ref == "REMOVED" or not entry.embedding:
                continue
            # Views added from a face later ruled out are dropped, or a
            # rejection would clear the label while still dragging matches
            # towards the wrong face.
            src = (entry.source_ref or "")
            if src.startswith("sighting:") and \
                    src.split(":", 1)[1] in rejected.get(entry.person_id, set()):
                continue
            galleries.setdefault(entry.person_id, []).append(entry.embedding)

        out: Dict[str, np.ndarray] = {}
        for pid, embs in galleries.items():
            arr = np.array(embs, dtype=np.float32)
            # Renaming re-appends the same vector, so drop exact repeats —
            # they add cost and no information.
            arr = np.unique(arr.round(6), axis=0)
            if arr.size:
                out[pid] = arr
        return out

    def get_all_embeddings(self) -> Dict[str, np.ndarray]:
        """Every person's face gallery, keyed by person_id.

        Shape is (N, D) — N confirmed views of that person. Callers score
        against the best-matching view; see FaceMatcher.cosine_similarity.
        """
        return self.get_galleries()

    def get_all_metadata(self) -> List[Dict[str, Any]]:
        """
        Get all active entries without embeddings (for API responses).

        Returns:
            List of entry metadata (no embeddings)
        """
        active = self._get_active_entries()
        return [
            {
                "person_id": entry.person_id,
                "label": entry.label,
                "added_ts": entry.added_ts,
                "source_ref": entry.source_ref,
                "metadata": entry.metadata,
            }
            for entry in active.values()
        ]
    
    def count(self) -> int:
        """Get total number of entries"""
        return len(self.load_all())


def effective_galleries() -> Dict[str, np.ndarray]:
    """Every saved face we know the name of, per person.

    The enrolled templates are only part of the answer. Each face sighting the
    archive has already attributed to someone is another view of them, and
    ignoring those meant a face could sit in the store labelled Paul while a
    new picture of Paul was compared against one photograph and declined.

    So: watchlist entries PLUS every attributed sighting, deduplicated. Widening
    what we compare against is the honest way to recognise more people —
    lowering the threshold would just mean guessing more often.
    """
    from alibi.watchlist.face_sighting_store import get_face_sighting_store

    from alibi.watchlist import rejections

    galleries = {pid: list(g) for pid, g in WatchlistStore().get_galleries().items()}
    rejected = rejections.all_rejections()
    try:
        for sight in get_face_sighting_store().load_all():
            pid = sight.matched_person_id
            if pid and pid in galleries and sight.embedding:
                # A face someone has ruled out must not creep back in.
                if sight.sighting_id in rejected.get(pid, set()):
                    continue
                galleries[pid].append(np.asarray(sight.embedding, dtype=np.float32))
    except Exception as e:
        print(f"[watchlist] could not read the face archive: {e}")

    out = {}
    for pid, views in galleries.items():
        arr = np.array([np.asarray(v, dtype=np.float32).ravel() for v in views],
                       dtype=np.float32)
        if arr.size:
            out[pid] = np.unique(arr.round(6), axis=0)
    return out
