"""
Hotlist Plate Store

JSONL storage for stolen vehicle license plates.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict

from alibi.encryption import get_encrypted_writer


@dataclass
class HotlistEntry:
    """Entry in the stolen vehicle hotlist"""
    plate: str  # Normalized plate number
    reason: str  # Reason for hotlist (stolen, wanted, etc.)
    added_ts: str  # ISO timestamp
    source_ref: str  # Reference to case/report
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        return {
            "plate": self.plate,
            "reason": self.reason,
            "added_ts": self.added_ts,
            "source_ref": self.source_ref,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HotlistEntry':
        """Create from dictionary"""
        return cls(
            plate=data["plate"],
            reason=data["reason"],
            added_ts=data["added_ts"],
            source_ref=data["source_ref"],
            metadata=data.get("metadata", {})
        )


class HotlistStore:
    """
    JSONL-based storage for hotlist plates.
    
    Append-only for audit trail.
    """
    
    def __init__(self, storage_path: str = "alibi/data/hotlist_plates.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()

        # Create file if it doesn't exist
        if not self.storage_path.exists():
            self.storage_path.touch()
            print(f"[HotlistStore] Created new hotlist file: {self.storage_path}")

        # Cache for fast lookups
        self._cache: Optional[Dict[str, HotlistEntry]] = None
        self._cache_time: Optional[float] = None
        self._cache_ttl: float = 300.0  # 5 minutes
    
    def add_entry(self, entry: HotlistEntry) -> None:
        """
        Add entry to hotlist (encrypted at rest).

        Args:
            entry: HotlistEntry to add
        """
        self._crypto.write_line(self.storage_path, entry.to_dict())
        
        # Invalidate cache
        self._cache = None
        
        print(f"[HotlistStore] Added entry: {entry.plate} - {entry.reason}")
    
    def load_all(self, use_cache: bool = True) -> List[HotlistEntry]:
        """
        Load all hotlist entries.

        Args:
            use_cache: Whether to use cached entries

        Returns:
            List of HotlistEntry objects
        """
        entries = []

        if not self.storage_path.exists():
            return entries

        for data in self._crypto.read_lines(self.storage_path):
            try:
                entries.append(HotlistEntry.from_dict(data))
            except Exception as e:
                print(f"[HotlistStore] Error loading entry: {e}")

        return entries
    
    def get_by_plate(self, plate: str, use_cache: bool = True) -> Optional[HotlistEntry]:
        """
        Get entry by plate number (returns most recent if multiple).
        
        Args:
            plate: Plate number to search for (will be normalized)
            use_cache: Whether to use cached entries
            
        Returns:
            HotlistEntry or None
        """
        # Use cache if available and fresh
        if use_cache:
            cache = self._get_cache()
            return cache.get(plate)
        
        # Direct lookup
        entries = self.load_all(use_cache=False)
        
        # Return most recent entry with matching plate
        for entry in reversed(entries):
            if entry.plate == plate:
                return entry
        
        return None
    
    def is_on_hotlist(self, plate: str) -> bool:
        """
        Check if plate is on active hotlist (excluding removed entries).
        
        Args:
            plate: Plate number to check
            
        Returns:
            True if on active hotlist
        """
        active_entries = self.get_active_entries()
        return any(entry.plate == plate for entry in active_entries)
    
    def _get_cache(self) -> Dict[str, HotlistEntry]:
        """Get cached hotlist (builds if needed)"""
        import time
        
        current_time = time.time()
        
        # Check if cache is valid
        if (self._cache is not None and 
            self._cache_time is not None and
            (current_time - self._cache_time) < self._cache_ttl):
            return self._cache
        
        # Rebuild cache
        entries = self.load_all(use_cache=False)
        self._cache = {}
        
        for entry in entries:
            # Use most recent entry for each plate
            self._cache[entry.plate] = entry
        
        self._cache_time = current_time
        
        return self._cache
    
    def remove_entry(self, plate: str) -> bool:
        """
        Remove entry from hotlist (marks as removed, doesn't delete).
        
        This appends a removal record for audit trail.
        
        Args:
            plate: Plate to remove
            
        Returns:
            True if entry existed and was removed
        """
        if not self.is_on_hotlist(plate):
            return False
        
        # Append removal record
        removal_entry = HotlistEntry(
            plate=plate,
            reason="REMOVED",
            added_ts=datetime.utcnow().isoformat(),
            source_ref="manual_removal",
            metadata={"action": "remove"}
        )
        
        self.add_entry(removal_entry)
        
        return True
    
    def get_active_entries(self) -> List[HotlistEntry]:
        """
        Get all active (non-removed) entries.
        
        Returns:
            List of active HotlistEntry objects
        """
        all_entries = self.load_all(use_cache=False)
        
        # Track which plates have been removed
        removed_plates = set()
        active_entries = []
        
        # Process in reverse order (most recent first)
        for entry in reversed(all_entries):
            if entry.reason == "REMOVED":
                removed_plates.add(entry.plate)
            elif entry.plate not in removed_plates:
                active_entries.append(entry)
        
        return list(reversed(active_entries))
    
    def count(self, active_only: bool = True) -> int:
        """
        Get total number of entries.
        
        Args:
            active_only: If True, only count active (non-removed) entries
            
        Returns:
            Entry count
        """
        if active_only:
            return len(self.get_active_entries())
        else:
            return len(self.load_all())
    
    def search(self, query: str) -> List[HotlistEntry]:
        """
        Search hotlist entries.
        
        Args:
            query: Search query (matches plate, reason, source_ref)
            
        Returns:
            List of matching entries
        """
        query_lower = query.lower()
        entries = self.get_active_entries()
        
        matches = []
        for entry in entries:
            if (query_lower in entry.plate.lower() or
                query_lower in entry.reason.lower() or
                query_lower in entry.source_ref.lower()):
                matches.append(entry)
        
        return matches
