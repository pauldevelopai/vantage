"""
Plate Registry Store

Maps license plates to expected vehicle make/model for mismatch detection.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class PlateRegistryEntry:
    """Entry in the plate registry"""
    plate: str  # Normalized plate number
    expected_make: str
    expected_model: str
    source_ref: str  # Reference to source data
    added_ts: str  # ISO timestamp
    expected_color: str = ""  # registered colour (enables colour-mismatch checks)
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        return {
            "plate": self.plate,
            "expected_make": self.expected_make,
            "expected_model": self.expected_model,
            "source_ref": self.source_ref,
            "added_ts": self.added_ts,
            "expected_color": self.expected_color,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlateRegistryEntry':
        """Create from dictionary"""
        return cls(
            plate=data["plate"],
            expected_make=data["expected_make"],
            expected_model=data["expected_model"],
            source_ref=data["source_ref"],
            added_ts=data["added_ts"],
            expected_color=data.get("expected_color", ""),
            metadata=data.get("metadata", {})
        )


class PlateRegistryStore:
    """
    JSONL-based storage for plate registry.
    
    Maps plates to expected vehicle make/model.
    """
    
    def __init__(self, storage_path: str = "alibi/data/plate_registry.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file if it doesn't exist
        if not self.storage_path.exists():
            self.storage_path.touch()
            print(f"[PlateRegistryStore] Created new registry file: {self.storage_path}")
        
        # Cache for fast lookups
        self._cache: Optional[Dict[str, PlateRegistryEntry]] = None
        self._cache_time: Optional[float] = None
        self._cache_ttl: float = 300.0  # 5 minutes
    
    def add_entry(self, entry: PlateRegistryEntry) -> None:
        """
        Add entry to registry.
        
        Args:
            entry: PlateRegistryEntry to add
        """
        with open(self.storage_path, 'a') as f:
            f.write(json.dumps(entry.to_dict()) + '\n')
        
        # Invalidate cache
        self._cache = None
        
        print(f"[PlateRegistryStore] Added entry: {entry.plate} -> {entry.expected_make} {entry.expected_model}")
    
    def load_all(self) -> List[PlateRegistryEntry]:
        """
        Load all registry entries.
        
        Returns:
            List of PlateRegistryEntry objects
        """
        entries = []
        
        if not self.storage_path.exists():
            return entries
        
        with open(self.storage_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    entries.append(PlateRegistryEntry.from_dict(data))
                except Exception as e:
                    print(f"[PlateRegistryStore] Error loading entry: {e}")
        
        return entries
    
    def get_by_plate(self, plate: str) -> Optional[PlateRegistryEntry]:
        """
        Get entry by plate number (returns most recent if multiple).
        
        Args:
            plate: Plate number to search for
            
        Returns:
            PlateRegistryEntry or None
        """
        cache = self._get_cache()
        return cache.get(plate)
    
    def is_registered(self, plate: str) -> bool:
        """
        Check if plate is in registry.
        
        Args:
            plate: Plate number to check
            
        Returns:
            True if registered
        """
        return self.get_by_plate(plate) is not None
    
    def _get_cache(self) -> Dict[str, PlateRegistryEntry]:
        """Get cached registry (builds if needed)"""
        import time
        
        current_time = time.time()
        
        # Check if cache is valid
        if (self._cache is not None and 
            self._cache_time is not None and
            (current_time - self._cache_time) < self._cache_ttl):
            return self._cache
        
        # Rebuild cache
        entries = self.load_all()
        self._cache = {}
        
        for entry in entries:
            # Use most recent entry for each plate
            self._cache[entry.plate] = entry
        
        self._cache_time = current_time
        
        return self._cache
    
    def count(self) -> int:
        """
        Get total number of entries.
        
        Returns:
            Entry count
        """
        return len(self.load_all())
