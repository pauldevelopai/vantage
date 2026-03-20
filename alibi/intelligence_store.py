"""
Intelligence Store - Knowledge base for crime detection and solving

Stores:
- Red flags (important incidents marked by operators)
- Tagged people (descriptions, not identities)
- Tagged places/locations
- Contextual information about the physical world
- Correlations between incidents
"""
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import hashlib

from alibi.encryption import get_encrypted_writer

# Storage files
RED_FLAGS_FILE = Path("alibi/data/red_flags.jsonl")
PEOPLE_TAGS_FILE = Path("alibi/data/people_tags.jsonl")
PLACE_TAGS_FILE = Path("alibi/data/place_tags.jsonl")
INTELLIGENCE_NOTES_FILE = Path("alibi/data/intelligence_notes.jsonl")

# Ensure directories exist
RED_FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class RedFlag:
    """A red-flagged incident or observation"""
    flag_id: str
    timestamp: str
    created_by: str
    severity: str  # "low", "medium", "high", "critical"
    category: str  # "suspicious_person", "suspicious_vehicle", "suspicious_activity", "location", "pattern", "other"
    description: str
    snapshot_url: Optional[str]
    analysis_id: Optional[str]  # Link to camera analysis
    location: Optional[str]
    tags: List[str]
    metadata: Dict[str, Any]
    resolved: bool
    resolved_by: Optional[str]
    resolved_at: Optional[str]
    resolution_notes: Optional[str]


@dataclass
class PersonTag:
    """Tagged person (description, not identification)"""
    person_tag_id: str
    timestamp: str
    created_by: str
    label: str  # "Person in red shirt", "Suspect 1", "Tall male, dark jacket"
    description: str  # Detailed description
    first_seen: str
    last_seen: str
    sightings: List[Dict[str, Any]]  # List of {timestamp, snapshot_url, location, analysis_id}
    associated_flags: List[str]  # Red flag IDs
    notes: str
    metadata: Dict[str, Any]


@dataclass
class PlaceTag:
    """Tagged location or place"""
    place_tag_id: str
    timestamp: str
    created_by: str
    name: str  # "North entrance", "Parking area", "Loading bay"
    description: str
    location_type: str  # "entrance", "exit", "parking", "restricted", "public", "other"
    coordinates: Optional[Dict[str, float]]  # lat/long if available
    notable_features: List[str]
    incidents: List[str]  # Red flag IDs at this location
    risk_level: str  # "low", "medium", "high"
    notes: str
    metadata: Dict[str, Any]


@dataclass
class IntelligenceNote:
    """Contextual intelligence note"""
    note_id: str
    timestamp: str
    created_by: str
    category: str  # "pattern", "correlation", "suspect_behavior", "location_info", "modus_operandi", "other"
    title: str
    content: str
    related_flags: List[str]
    related_people: List[str]
    related_places: List[str]
    confidence: str  # "low", "medium", "high"
    actionable: bool
    tags: List[str]
    metadata: Dict[str, Any]


class IntelligenceStore:
    """Manages intelligence data for crime detection and solving"""
    
    def __init__(self):
        self.red_flags_file = RED_FLAGS_FILE
        self.people_tags_file = PEOPLE_TAGS_FILE
        self.place_tags_file = PLACE_TAGS_FILE
        self.intelligence_notes_file = INTELLIGENCE_NOTES_FILE
        self._crypto = get_encrypted_writer()
    
    # RED FLAGS
    
    def add_red_flag(self, flag: RedFlag):
        """Add a red flag (encrypted at rest)"""
        self._crypto.write_line(self.red_flags_file, asdict(flag))
    
    def get_red_flags(self, 
                      resolved: Optional[bool] = None,
                      severity: Optional[str] = None,
                      category: Optional[str] = None,
                      limit: int = 100) -> List[RedFlag]:
        """Get red flags with filters"""
        if not self.red_flags_file.exists():
            return []
        
        flags = []
        for data in self._crypto.read_lines(self.red_flags_file):
            try:
                flag = RedFlag(**data)

                # Apply filters
                if resolved is not None and flag.resolved != resolved:
                    continue
                if severity and flag.severity != severity:
                    continue
                if category and flag.category != category:
                    continue

                flags.append(flag)
            except:
                continue
        
        # Sort by timestamp, most recent first
        flags.sort(key=lambda x: x.timestamp, reverse=True)
        return flags[:limit]
    
    def resolve_red_flag(self, flag_id: str, resolved_by: str, notes: str):
        """Mark a red flag as resolved"""
        flags = []
        for data in self._crypto.read_lines(self.red_flags_file):
            try:
                if data['flag_id'] == flag_id:
                    data['resolved'] = True
                    data['resolved_by'] = resolved_by
                    data['resolved_at'] = datetime.utcnow().isoformat()
                    data['resolution_notes'] = notes
                flags.append(data)
            except:
                continue

        # Rewrite file (encrypted)
        with open(self.red_flags_file, 'w') as f:
            for flag_data in flags:
                f.write(self._crypto.encrypt_line(flag_data) + '\n')
    
    # PEOPLE TAGS
    
    def add_person_tag(self, person: PersonTag):
        """Add a person tag (encrypted at rest)"""
        self._crypto.write_line(self.people_tags_file, asdict(person))
    
    def get_person_tags(self, limit: int = 100) -> List[PersonTag]:
        """Get all person tags"""
        if not self.people_tags_file.exists():
            return []
        
        people = []
        for data in self._crypto.read_lines(self.people_tags_file):
            try:
                people.append(PersonTag(**data))
            except:
                continue
        
        # Sort by last seen, most recent first
        people.sort(key=lambda x: x.last_seen, reverse=True)
        return people[:limit]
    
    def update_person_tag(self, person_tag_id: str, updates: Dict):
        """Update a person tag"""
        people = []
        for data in self._crypto.read_lines(self.people_tags_file):
            try:
                if data['person_tag_id'] == person_tag_id:
                    data.update(updates)
                people.append(data)
            except:
                continue

        # Rewrite file (encrypted)
        with open(self.people_tags_file, 'w') as f:
            for person_data in people:
                f.write(self._crypto.encrypt_line(person_data) + '\n')
    
    # PLACE TAGS
    
    def add_place_tag(self, place: PlaceTag):
        """Add a place tag (encrypted at rest)"""
        self._crypto.write_line(self.place_tags_file, asdict(place))
    
    def get_place_tags(self, risk_level: Optional[str] = None, limit: int = 100) -> List[PlaceTag]:
        """Get place tags"""
        if not self.place_tags_file.exists():
            return []
        
        places = []
        for data in self._crypto.read_lines(self.place_tags_file):
            try:
                place = PlaceTag(**data)

                if risk_level and place.risk_level != risk_level:
                    continue

                places.append(place)
            except:
                continue
        
        # Sort by number of incidents, highest first
        places.sort(key=lambda x: len(x.incidents), reverse=True)
        return places[:limit]
    
    # INTELLIGENCE NOTES
    
    def add_intelligence_note(self, note: IntelligenceNote):
        """Add an intelligence note (encrypted at rest)"""
        self._crypto.write_line(self.intelligence_notes_file, asdict(note))
    
    def get_intelligence_notes(self, 
                               category: Optional[str] = None,
                               actionable: Optional[bool] = None,
                               limit: int = 100) -> List[IntelligenceNote]:
        """Get intelligence notes"""
        if not self.intelligence_notes_file.exists():
            return []
        
        notes = []
        for data in self._crypto.read_lines(self.intelligence_notes_file):
            try:
                note = IntelligenceNote(**data)

                if category and note.category != category:
                    continue
                if actionable is not None and note.actionable != actionable:
                    continue

                notes.append(note)
            except:
                continue
        
        # Sort by timestamp, most recent first
        notes.sort(key=lambda x: x.timestamp, reverse=True)
        return notes[:limit]
    
    # SEARCH & CORRELATION
    
    def search(self, query: str) -> Dict[str, List]:
        """Search across all intelligence data"""
        query_lower = query.lower()
        
        results = {
            "red_flags": [],
            "people": [],
            "places": [],
            "notes": []
        }
        
        # Search red flags
        for flag in self.get_red_flags(limit=1000):
            if (query_lower in flag.description.lower() or
                query_lower in flag.category.lower() or
                any(query_lower in tag.lower() for tag in flag.tags)):
                results["red_flags"].append(flag)
        
        # Search people
        for person in self.get_person_tags(limit=1000):
            if (query_lower in person.label.lower() or
                query_lower in person.description.lower() or
                query_lower in person.notes.lower()):
                results["people"].append(person)
        
        # Search places
        for place in self.get_place_tags(limit=1000):
            if (query_lower in place.name.lower() or
                query_lower in place.description.lower() or
                query_lower in place.notes.lower()):
                results["places"].append(place)
        
        # Search intelligence notes
        for note in self.get_intelligence_notes(limit=1000):
            if (query_lower in note.title.lower() or
                query_lower in note.content.lower() or
                any(query_lower in tag.lower() for tag in note.tags)):
                results["notes"].append(note)
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get intelligence statistics"""
        flags = self.get_red_flags(limit=10000)
        people = self.get_person_tags(limit=10000)
        places = self.get_place_tags(limit=10000)
        notes = self.get_intelligence_notes(limit=10000)
        
        return {
            "total_red_flags": len(flags),
            "unresolved_flags": len([f for f in flags if not f.resolved]),
            "critical_flags": len([f for f in flags if f.severity == "critical"]),
            "total_people_tagged": len(people),
            "total_places_tagged": len(places),
            "high_risk_places": len([p for p in places if p.risk_level == "high"]),
            "total_intelligence_notes": len(notes),
            "actionable_notes": len([n for n in notes if n.actionable])
        }


# Global instance
_intelligence_store = None

def get_intelligence_store() -> IntelligenceStore:
    """Get the global intelligence store"""
    global _intelligence_store
    if _intelligence_store is None:
        _intelligence_store = IntelligenceStore()
    return _intelligence_store
