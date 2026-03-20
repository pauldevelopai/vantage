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

    def get_all_embeddings(self) -> Dict[str, np.ndarray]:
        """
        Get all active embeddings as dictionary.

        Returns:
            Dict mapping person_id to embedding array
        """
        active = self._get_active_entries()
        return {pid: entry.get_embedding_array() for pid, entry in active.items()}

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
