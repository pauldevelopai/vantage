"""
Vehicle Sightings Store

JSONL storage for continuous vehicle sightings indexing.
Enables search by make, model, color, time, location.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict


@dataclass
class VehicleSighting:
    """A recorded vehicle sighting"""
    sighting_id: str
    camera_id: str
    ts: str  # ISO timestamp
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    color: str
    make: str
    model: str
    confidence: float  # Overall detection confidence
    snapshot_url: Optional[str] = None
    clip_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        return {
            "sighting_id": self.sighting_id,
            "camera_id": self.camera_id,
            "ts": self.ts,
            "bbox": list(self.bbox),
            "color": self.color,
            "make": self.make,
            "model": self.model,
            "confidence": self.confidence,
            "snapshot_url": self.snapshot_url,
            "clip_url": self.clip_url,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VehicleSighting':
        """Create from dictionary"""
        return cls(
            sighting_id=data["sighting_id"],
            camera_id=data["camera_id"],
            ts=data["ts"],
            bbox=tuple(data["bbox"]),
            color=data["color"],
            make=data["make"],
            model=data["model"],
            confidence=data["confidence"],
            snapshot_url=data.get("snapshot_url"),
            clip_url=data.get("clip_url"),
            metadata=data.get("metadata", {})
        )


class VehicleSightingsStore:
    """
    JSONL-based storage for vehicle sightings.
    
    Continuously appends sightings for searchable index.
    """
    
    def __init__(self, storage_path: str = "alibi/data/vehicle_sightings.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file if it doesn't exist
        if not self.storage_path.exists():
            self.storage_path.touch()
            print(f"[VehicleSightingsStore] Created new sightings file: {self.storage_path}")
    
    def add_sighting(self, sighting: VehicleSighting) -> None:
        """
        Add sighting to store.
        
        Args:
            sighting: VehicleSighting to add
        """
        with open(self.storage_path, 'a') as f:
            f.write(json.dumps(sighting.to_dict()) + '\n')
    
    def load_all(self, limit: Optional[int] = None) -> List[VehicleSighting]:
        """
        Load all sightings (or limited number).
        
        Args:
            limit: Maximum number of sightings to load (most recent)
            
        Returns:
            List of VehicleSighting objects
        """
        sightings = []
        
        if not self.storage_path.exists():
            return sightings
        
        with open(self.storage_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    sightings.append(VehicleSighting.from_dict(data))
                except Exception as e:
                    print(f"[VehicleSightingsStore] Error loading sighting: {e}")
        
        # If limit specified, return most recent
        if limit and len(sightings) > limit:
            sightings = sightings[-limit:]
        
        return sightings
    
    def search(
        self,
        make: Optional[str] = None,
        model: Optional[str] = None,
        color: Optional[str] = None,
        camera_id: Optional[str] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: int = 100
    ) -> List[VehicleSighting]:
        """
        Search sightings by criteria.
        
        Args:
            make: Vehicle make (case-insensitive partial match)
            model: Vehicle model (case-insensitive partial match)
            color: Vehicle color (case-insensitive)
            camera_id: Camera ID (exact match)
            from_ts: Start timestamp (ISO format)
            to_ts: End timestamp (ISO format)
            limit: Maximum results to return
            
        Returns:
            List of matching VehicleSighting objects (sorted by timestamp desc)
        """
        # Load all sightings (could be optimized with indexing)
        all_sightings = self.load_all()
        
        matches = []
        
        for sighting in all_sightings:
            # Apply filters
            if make and make.lower() not in sighting.make.lower():
                continue
            
            if model and model.lower() not in sighting.model.lower():
                continue
            
            if color and color.lower() != sighting.color.lower():
                continue
            
            if camera_id and camera_id != sighting.camera_id:
                continue
            
            # Time range filter
            if from_ts:
                try:
                    sighting_time = datetime.fromisoformat(sighting.ts)
                    from_time = datetime.fromisoformat(from_ts)
                    if sighting_time < from_time:
                        continue
                except:
                    pass
            
            if to_ts:
                try:
                    sighting_time = datetime.fromisoformat(sighting.ts)
                    to_time = datetime.fromisoformat(to_ts)
                    if sighting_time > to_time:
                        continue
                except:
                    pass
            
            matches.append(sighting)
        
        # Sort by timestamp (most recent first)
        matches.sort(key=lambda s: s.ts, reverse=True)
        
        # Apply limit
        return matches[:limit]
    
    def count(self) -> int:
        """
        Get total number of sightings.
        
        Returns:
            Total count
        """
        return len(self.load_all())
    
    def get_by_id(self, sighting_id: str) -> Optional[VehicleSighting]:
        """
        Get sighting by ID.
        
        Args:
            sighting_id: Sighting ID
            
        Returns:
            VehicleSighting or None
        """
        all_sightings = self.load_all()
        
        for sighting in all_sightings:
            if sighting.sighting_id == sighting_id:
                return sighting
        
        return None
    
    def search_by_plate(self, plate_query: str, limit: int = 100) -> List[VehicleSighting]:
        """
        Search sightings by license plate text stored in metadata.

        Args:
            plate_query: Plate text to search for (case-insensitive partial match)
            limit: Maximum results

        Returns:
            Matching sightings sorted by timestamp desc
        """
        query_upper = plate_query.upper().replace(" ", "")
        all_sightings = self.load_all()
        matches = []

        for s in all_sightings:
            plate_text = (s.metadata or {}).get("plate_text", "")
            if plate_text and query_upper in plate_text.upper().replace(" ", ""):
                matches.append(s)

        matches.sort(key=lambda s: s.ts, reverse=True)
        return matches[:limit]

    def get_recent(self, limit: int = 100) -> List[VehicleSighting]:
        """
        Get most recent sightings.
        
        Args:
            limit: Number of sightings to return
            
        Returns:
            List of recent VehicleSighting objects
        """
        all_sightings = self.load_all()
        
        # Sort by timestamp (most recent first)
        all_sightings.sort(key=lambda s: s.ts, reverse=True)
        
        return all_sightings[:limit]
