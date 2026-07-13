"""
Vantage Incident Grouping Logic

Deterministic rules for grouping camera events into incidents.
"""

from datetime import datetime, timedelta
from typing import Optional, List
import hashlib

from alibi.schemas import CameraEvent, Incident, IncidentStatus
from alibi.alibi_store import VantageStore
from alibi.settings import VantageSettings


class IncidentGrouper:
    """Groups camera events into incidents with deduplication"""
    
    def __init__(self, store: VantageStore, settings: VantageSettings):
        self.store = store
        self.settings = settings
    
    def process_event(self, event: CameraEvent) -> Incident:
        """
        Process a camera event and return the incident it belongs to.
        
        Rules:
        1. Dedup: If same camera+zone+event_type within 30s, attach to existing incident
        2. Grouping: If same camera+zone with compatible event_type within 5min, merge
        3. Otherwise: Create new incident
        """
        # Check for deduplication first
        existing_incident = self._find_duplicate_incident(event)
        if existing_incident:
            # Attach to existing incident (if not already attached)
            if not any(e.event_id == event.event_id for e in existing_incident.events):
                existing_incident.events.append(event)
                existing_incident.updated_ts = datetime.utcnow()
            return existing_incident
        
        # Check for grouping
        mergeable_incident = self._find_mergeable_incident(event)
        if mergeable_incident:
            # Add to existing incident
            mergeable_incident.events.append(event)
            mergeable_incident.updated_ts = datetime.utcnow()
            return mergeable_incident
        
        # Create new incident
        return self._create_new_incident(event)
    
    def _find_duplicate_incident(self, event: CameraEvent) -> Optional[Incident]:
        """
        Find incident that matches dedup criteria.
        
        Dedup rule: Same camera_id + zone_id + event_type within dedup_window_seconds
        """
        dedup_window = timedelta(seconds=self.settings.dedup_window_seconds)
        cutoff_time = event.ts - dedup_window
        
        # Get recent incidents
        recent_incidents = self.store.list_incidents(limit=50)
        
        for incident in recent_incidents:
            # Skip if too old
            if incident.updated_ts < cutoff_time:
                continue
            
            # Check if any event in this incident matches dedup criteria
            for existing_event in incident.events:
                if (existing_event.camera_id == event.camera_id and
                    existing_event.zone_id == event.zone_id and
                    existing_event.event_type == event.event_type and
                    abs((existing_event.ts - event.ts).total_seconds()) <= self.settings.dedup_window_seconds):
                    return incident
        
        return None
    
    def _find_mergeable_incident(self, event: CameraEvent) -> Optional[Incident]:
        """
        Find incident that matches grouping criteria.
        
        Grouping rule: Same camera_id + zone_id, compatible event_type, within merge_window
        """
        merge_window = timedelta(seconds=self.settings.merge_window_seconds)
        cutoff_time = event.ts - merge_window
        
        # Get recent incidents
        recent_incidents = self.store.list_incidents(limit=50)
        
        for incident in recent_incidents:
            # Skip if too old
            if incident.updated_ts < cutoff_time:
                continue
            
            # Check if incident is compatible
            if self._is_incident_compatible(incident, event):
                return incident
        
        return None
    
    def _is_incident_compatible(self, incident: Incident, event: CameraEvent) -> bool:
        """Check if incident is compatible for grouping with event"""
        # Must have at least one event
        if not incident.events:
            return False
        
        # Check each event in incident
        for existing_event in incident.events:
            # Same camera and zone?
            if (existing_event.camera_id != event.camera_id or
                existing_event.zone_id != event.zone_id):
                continue
            
            # Compatible event types?
            if self.settings.are_event_types_compatible(
                existing_event.event_type,
                event.event_type
            ):
                return True
        
        return False
    
    def _create_new_incident(self, event: CameraEvent) -> Incident:
        """Create a new incident from an event"""
        incident_id = self._generate_incident_id(event)
        
        return Incident(
            incident_id=incident_id,
            status=IncidentStatus.NEW,
            created_ts=event.ts,
            updated_ts=event.ts,
            events=[event],
            metadata={},
        )
    
    def _generate_incident_id(self, event: CameraEvent) -> str:
        """Generate deterministic incident ID"""
        # Use timestamp + camera + zone for uniqueness
        base = f"{event.ts.isoformat()}_{event.camera_id}_{event.zone_id}"
        hash_suffix = hashlib.md5(base.encode()).hexdigest()[:8]
        timestamp_str = event.ts.strftime("%Y%m%d_%H%M%S")
        return f"inc_{timestamp_str}_{hash_suffix}"


def process_camera_event(
    event: CameraEvent,
    store: VantageStore,
    settings: VantageSettings
) -> Incident:
    """
    Process a camera event and return the incident it belongs to.
    
    This is the main entry point for event processing.
    """
    grouper = IncidentGrouper(store, settings)
    return grouper.process_event(event)
