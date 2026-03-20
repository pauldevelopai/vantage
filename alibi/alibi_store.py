"""
Alibi Storage Layer

Append-only JSONL storage for events, incidents, decisions, and audit logs.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from alibi.schemas import (
    CameraEvent,
    Incident,
    IncidentStatus,
    Decision,
)
from alibi.encryption import get_encrypted_writer


class AlibiStore:
    """Append-only JSONL storage manager"""
    
    def __init__(self, data_dir: str = "alibi/data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.events_file = self.data_dir / "events.jsonl"
        self.incidents_file = self.data_dir / "incidents.jsonl"
        self.decisions_file = self.data_dir / "decisions.jsonl"
        self.audit_file = self.data_dir / "audit.jsonl"

        self._crypto = get_encrypted_writer()

        # Ensure files exist
        for file in [self.events_file, self.incidents_file, self.decisions_file, self.audit_file]:
            file.touch(exist_ok=True)
    
    # Event operations
    
    def append_event(self, event: CameraEvent) -> None:
        """Append camera event to events.jsonl (encrypted at rest)"""
        event_dict = self._serialize_event(event)
        event_dict["_stored_at"] = datetime.utcnow().isoformat()
        self._crypto.write_line(self.events_file, event_dict)
    
    def list_events(
        self,
        camera_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        limit: int = 100
    ) -> List[CameraEvent]:
        """List events with optional filters"""
        events = []

        if not self.events_file.exists():
            return events

        for event_dict in self._crypto.read_lines(self.events_file):
            # Apply filters
            if camera_id and event_dict.get("camera_id") != camera_id:
                continue
            if zone_id and event_dict.get("zone_id") != zone_id:
                continue

            events.append(self._deserialize_event(event_dict))

            if len(events) >= limit:
                break

        return list(reversed(events))  # Most recent first
    
    def get_events_by_ids(self, event_ids: List[str]) -> List[CameraEvent]:
        """Get events by their IDs"""
        event_id_set = set(event_ids)
        events = []

        if not self.events_file.exists():
            return events

        for event_dict in self._crypto.read_lines(self.events_file):
            if event_dict.get("event_id") in event_id_set:
                events.append(self._deserialize_event(event_dict))

        return events
    
    # Incident operations
    
    def upsert_incident(self, incident: Incident, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Upsert incident to incidents.jsonl.
        
        Appends a new version of the incident (append-only).
        To get latest version, read file backwards.
        """
        incident_dict = self._serialize_incident(incident)
        incident_dict["_stored_at"] = datetime.utcnow().isoformat()
        incident_dict["_version"] = datetime.utcnow().timestamp()

        if metadata:
            incident_dict["_metadata"] = metadata

        self._crypto.write_line(self.incidents_file, incident_dict)
    
    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get latest version of incident by ID"""
        if not self.incidents_file.exists():
            return None

        latest = None
        for incident_dict in self._crypto.read_lines(self.incidents_file):
            if incident_dict.get("incident_id") == incident_id:
                latest = incident_dict

        if latest:
            return self._deserialize_incident(latest)
        return None
    
    def get_incident_with_metadata(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Get incident with full metadata (plan, alert, validation)"""
        if not self.incidents_file.exists():
            return None

        latest = None
        for incident_dict in self._crypto.read_lines(self.incidents_file):
            if incident_dict.get("incident_id") == incident_id:
                latest = incident_dict

        return latest
    
    def list_incidents(
        self,
        status: Optional[IncidentStatus] = None,
        limit: int = 100
    ) -> List[Incident]:
        """List incidents (returns latest version of each)"""
        incidents_by_id = {}

        if not self.incidents_file.exists():
            return []

        for incident_dict in self._crypto.read_lines(self.incidents_file):
            incident_id = incident_dict.get("incident_id")

            if incident_id:
                if incident_id not in incidents_by_id:
                    incidents_by_id[incident_id] = incident_dict
                else:
                    current_version = incidents_by_id[incident_id].get("_version", 0)
                    new_version = incident_dict.get("_version", 0)
                    if new_version > current_version:
                        incidents_by_id[incident_id] = incident_dict
        
        # Convert to Incident objects and filter
        incidents = []
        for incident_dict in incidents_by_id.values():
            incident = self._deserialize_incident(incident_dict)
            
            # Apply filters
            if status and incident.status != status:
                continue
            
            incidents.append(incident)
        
        # Sort by created_ts descending
        incidents.sort(key=lambda i: i.created_ts, reverse=True)
        
        return incidents[:limit]
    
    def list_incidents_with_metadata(
        self,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List incidents with metadata (plan, alert, validation)"""
        incidents_by_id = {}

        if not self.incidents_file.exists():
            return []

        for incident_dict in self._crypto.read_lines(self.incidents_file):
            incident_id = incident_dict.get("incident_id")

            if incident_id:
                if incident_id not in incidents_by_id:
                    incidents_by_id[incident_id] = incident_dict
                else:
                    current_version = incidents_by_id[incident_id].get("_version", 0)
                    new_version = incident_dict.get("_version", 0)
                    if new_version > current_version:
                        incidents_by_id[incident_id] = incident_dict
        
        # Filter and sort
        results = []
        for incident_dict in incidents_by_id.values():
            if status and incident_dict.get("status") != status:
                continue
            results.append(incident_dict)
        
        results.sort(key=lambda x: x.get("created_ts", ""), reverse=True)
        
        return results[:limit]
    
    # Decision operations
    
    def append_decision(self, decision: Decision) -> None:
        """Append operator decision to decisions.jsonl (encrypted at rest)"""
        decision_dict = self._serialize_decision(decision)
        decision_dict["_stored_at"] = datetime.utcnow().isoformat()
        self._crypto.write_line(self.decisions_file, decision_dict)
    
    def list_decisions(
        self,
        incident_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Decision]:
        """List decisions with optional filter by incident_id"""
        decisions = []

        if not self.decisions_file.exists():
            return decisions

        for decision_dict in self._crypto.read_lines(self.decisions_file):
            if incident_id and decision_dict.get("incident_id") != incident_id:
                continue

            decisions.append(self._deserialize_decision(decision_dict))

            if len(decisions) >= limit:
                break

        return list(reversed(decisions))  # Most recent first
    
    # Audit operations
    
    def append_audit(self, action: str, data: Dict[str, Any]) -> None:
        """Append audit log entry (encrypted at rest)"""
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "data": data,
        }
        self._crypto.write_line(self.audit_file, audit_entry)
    
    # Serialization helpers
    
    def _serialize_event(self, event: CameraEvent) -> Dict[str, Any]:
        """Serialize CameraEvent to dict"""
        data = asdict(event)
        data["ts"] = event.ts.isoformat()
        return data
    
    def _deserialize_event(self, data: Dict[str, Any]) -> CameraEvent:
        """Deserialize dict to CameraEvent"""
        data = data.copy()
        data.pop("_stored_at", None)
        data["ts"] = datetime.fromisoformat(data["ts"])
        return CameraEvent(**data)
    
    def _serialize_incident(self, incident: Incident) -> Dict[str, Any]:
        """Serialize Incident to dict"""
        data = {
            "incident_id": incident.incident_id,
            "status": incident.status.value if hasattr(incident.status, 'value') else incident.status,
            "created_ts": incident.created_ts.isoformat(),
            "updated_ts": incident.updated_ts.isoformat(),
            "event_ids": [e.event_id for e in incident.events],
            "metadata": incident.metadata,
        }
        return data
    
    def _deserialize_incident(self, data: Dict[str, Any]) -> Incident:
        """Deserialize dict to Incident"""
        # Load events by IDs
        event_ids = data.get("event_ids", [])
        events = self.get_events_by_ids(event_ids)
        
        return Incident(
            incident_id=data["incident_id"],
            status=IncidentStatus(data["status"]),
            created_ts=datetime.fromisoformat(data["created_ts"]),
            updated_ts=datetime.fromisoformat(data["updated_ts"]),
            events=events,
            metadata=data.get("metadata", {}),
        )
    
    def _serialize_decision(self, decision: Decision) -> Dict[str, Any]:
        """Serialize Decision to dict"""
        return {
            "incident_id": decision.incident_id,
            "decision_ts": decision.decision_ts.isoformat(),
            "action_taken": decision.action_taken,
            "operator_notes": decision.operator_notes,
            "was_true_positive": decision.was_true_positive,
            "metadata": decision.metadata,
        }
    
    def _deserialize_decision(self, data: Dict[str, Any]) -> Decision:
        """Deserialize dict to Decision"""
        data = data.copy()
        data.pop("_stored_at", None)
        data["decision_ts"] = datetime.fromisoformat(data["decision_ts"])
        return Decision(**data)


# Global store instance
_store_instance = None


def get_store(data_dir: str = "alibi/data") -> AlibiStore:
    """Get or create global store instance"""
    global _store_instance
    if _store_instance is None:
        _store_instance = AlibiStore(data_dir)
    return _store_instance
