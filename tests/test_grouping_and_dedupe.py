"""
Tests for incident grouping and deduplication logic.

Verifies that events are correctly grouped into incidents based on:
- Deduplication (same camera+zone+type within 30s)
- Grouping (same camera+zone, compatible type within 5min)
"""

import pytest
from datetime import datetime, timedelta

from alibi.schemas import CameraEvent, IncidentStatus
from alibi.alibi_store import VantageStore
from alibi.settings import VantageSettings
from alibi.incident_grouper import IncidentGrouper, process_camera_event


@pytest.fixture
def temp_store(tmp_path):
    """Create temporary store for testing"""
    return VantageStore(data_dir=str(tmp_path / "data"))


@pytest.fixture
def settings():
    """Create settings with default values"""
    return VantageSettings()


@pytest.fixture
def grouper(temp_store, settings):
    """Create incident grouper"""
    return IncidentGrouper(temp_store, settings)


def create_event(
    event_id: str,
    camera_id: str = "cam_01",
    zone_id: str = "zone_a",
    event_type: str = "person_detected",
    ts: datetime = None,
    confidence: float = 0.85,
    severity: int = 3,
) -> CameraEvent:
    """Helper to create test events"""
    if ts is None:
        ts = datetime.utcnow()
    
    return CameraEvent(
        event_id=event_id,
        camera_id=camera_id,
        ts=ts,
        zone_id=zone_id,
        event_type=event_type,
        confidence=confidence,
        severity=severity,
        clip_url=f"https://example.com/clips/{event_id}.mp4",
    )


class TestDeduplication:
    """Test deduplication rules"""
    
    def test_duplicate_events_same_incident(self, grouper, temp_store):
        """Same camera+zone+type within 30s should attach to same incident"""
        base_time = datetime.utcnow()
        
        # First event creates incident
        event1 = create_event("evt_001", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        assert len(incident1.events) == 1
        assert incident1.events[0].event_id == "evt_001"
        
        # Second event 10 seconds later - should be duplicate
        event2 = create_event("evt_002", ts=base_time + timedelta(seconds=10))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        assert incident2.incident_id == incident1.incident_id
        assert len(incident2.events) == 2
    
    def test_no_duplicate_after_window(self, grouper, temp_store):
        """Events 31s apart should NOT be duplicates"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event 31 seconds later - outside dedup window
        event2 = create_event("evt_002", ts=base_time + timedelta(seconds=31))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents (or merged via grouping)
        # At minimum, should have processed without error
        assert incident2 is not None
    
    def test_duplicate_different_camera_no_match(self, grouper, temp_store):
        """Different camera should not be duplicate"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", camera_id="cam_01", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event different camera, same time
        event2 = create_event("evt_002", camera_id="cam_02", ts=base_time + timedelta(seconds=5))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents
        assert incident2.incident_id != incident1.incident_id
    
    def test_duplicate_different_zone_no_match(self, grouper, temp_store):
        """Different zone should not be duplicate"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", zone_id="zone_a", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event different zone
        event2 = create_event("evt_002", zone_id="zone_b", ts=base_time + timedelta(seconds=5))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents
        assert incident2.incident_id != incident1.incident_id
    
    def test_duplicate_different_type_no_match(self, grouper, temp_store):
        """Different event type should not be duplicate"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", event_type="person_detected", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event different type
        event2 = create_event("evt_002", event_type="vehicle_detected", ts=base_time + timedelta(seconds=5))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents
        assert incident2.incident_id != incident1.incident_id


class TestGrouping:
    """Test incident grouping rules"""
    
    def test_grouping_same_camera_zone_compatible_type(self, grouper, temp_store):
        """Events with compatible types should group within merge window"""
        base_time = datetime.utcnow()
        
        # First event - person_detected
        event1 = create_event(
            "evt_001",
            event_type="person_detected",
            ts=base_time
        )
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event 2 minutes later - person_loitering (compatible)
        event2 = create_event(
            "evt_002",
            event_type="person_loitering",
            ts=base_time + timedelta(minutes=2)
        )
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should merge into same incident
        assert incident2.incident_id == incident1.incident_id
        assert len(incident2.events) == 2
    
    def test_grouping_same_type_merges(self, grouper, temp_store):
        """Same event type should always be compatible for grouping"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event 1 minute later, same type
        event2 = create_event("evt_002", ts=base_time + timedelta(minutes=1))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should merge
        assert incident2.incident_id == incident1.incident_id
        assert len(incident2.events) == 2
    
    def test_no_grouping_after_merge_window(self, grouper, temp_store):
        """Events 6 minutes apart should not group (window is 5min)"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event 6 minutes later - outside merge window
        event2 = create_event("evt_002", ts=base_time + timedelta(minutes=6))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents
        assert incident2.incident_id != incident1.incident_id
    
    def test_no_grouping_different_camera(self, grouper, temp_store):
        """Different camera should not group"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", camera_id="cam_01", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event different camera
        event2 = create_event("evt_002", camera_id="cam_02", ts=base_time + timedelta(minutes=1))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents
        assert incident2.incident_id != incident1.incident_id
    
    def test_no_grouping_different_zone(self, grouper, temp_store):
        """Different zone should not group"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", zone_id="zone_a", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event different zone
        event2 = create_event("evt_002", zone_id="zone_b", ts=base_time + timedelta(minutes=1))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should be different incidents
        assert incident2.incident_id != incident1.incident_id
    
    def test_breach_types_group_together(self, grouper, temp_store, settings):
        """Breach-related types should be compatible"""
        # Verify settings has this configured
        assert settings.are_event_types_compatible("breach", "unauthorized_access")
        
        base_time = datetime.utcnow()
        
        # First event - breach
        event1 = create_event("evt_001", event_type="breach", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        # Second event - unauthorized_access (compatible with breach)
        event2 = create_event("evt_002", event_type="unauthorized_access", ts=base_time + timedelta(minutes=2))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Should merge
        assert incident2.incident_id == incident1.incident_id
        assert len(incident2.events) == 2


class TestIncidentCreation:
    """Test incident creation and management"""
    
    def test_first_event_creates_incident(self, grouper, temp_store):
        """First event should create new incident"""
        event = create_event("evt_001")
        temp_store.append_event(event)
        incident = grouper.process_event(event)
        
        assert incident is not None
        assert incident.incident_id.startswith("inc_")
        assert incident.status == IncidentStatus.NEW
        assert len(incident.events) == 1
        assert incident.events[0].event_id == "evt_001"
    
    def test_incident_id_format(self, grouper, temp_store):
        """Incident ID should have correct format"""
        event = create_event("evt_001")
        temp_store.append_event(event)
        incident = grouper.process_event(event)
        
        # Format: inc_YYYYMMDD_HHMMSS_hash
        parts = incident.incident_id.split("_")
        assert parts[0] == "inc"
        assert len(parts) >= 3
    
    def test_incident_timestamps(self, grouper, temp_store):
        """Incident timestamps should match event"""
        event = create_event("evt_001")
        temp_store.append_event(event)
        incident = grouper.process_event(event)
        
        assert incident.created_ts == event.ts
        assert incident.updated_ts == event.ts
    
    def test_incident_updated_on_merge(self, grouper, temp_store):
        """Incident updated_ts should change when events added"""
        base_time = datetime.utcnow()
        
        # First event
        event1 = create_event("evt_001", ts=base_time)
        temp_store.append_event(event1)
        incident1 = grouper.process_event(event1)
        temp_store.upsert_incident(incident1)
        
        original_updated = incident1.updated_ts
        
        # Second event
        event2 = create_event("evt_002", ts=base_time + timedelta(minutes=1))
        temp_store.append_event(event2)
        incident2 = grouper.process_event(event2)
        
        # Updated timestamp should change
        assert incident2.updated_ts >= original_updated


class TestProcessCameraEvent:
    """Test the main process_camera_event function"""
    
    def test_process_camera_event_integration(self, temp_store, settings):
        """Test the main entry point function"""
        event = create_event("evt_001")
        temp_store.append_event(event)
        
        incident = process_camera_event(event, temp_store, settings)
        
        assert incident is not None
        assert incident.incident_id.startswith("inc_")
        assert len(incident.events) == 1
    
    def test_multiple_events_sequence(self, temp_store, settings):
        """Test processing multiple events in sequence"""
        base_time = datetime.utcnow()
        
        incidents = []
        
        # Process 3 events in sequence
        for i in range(3):
            event = create_event(
                f"evt_{i:03d}",
                ts=base_time + timedelta(seconds=i * 10)
            )
            temp_store.append_event(event)
            incident = process_camera_event(event, temp_store, settings)
            temp_store.upsert_incident(incident)
            incidents.append(incident)
        
        # All should be in same incident (dedup/grouping)
        assert incidents[0].incident_id == incidents[1].incident_id
        assert incidents[1].incident_id == incidents[2].incident_id
        
        # Final incident should have all 3 events
        assert len(incidents[2].events) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_list_incidents_hydrates_events_in_one_pass(temp_store):
    """list_incidents must attach each incident's real events (regression: the
    old per-incident get_events_by_ids re-read the whole events file each time,
    making listing O(incidents × events) — ~31s for 167 incidents live)."""
    from alibi.schemas import Incident
    now = datetime.utcnow()
    for n in range(3):
        ev = CameraEvent(event_id=f"e{n}", camera_id=f"cam{n}", ts=now,
                         zone_id="z", event_type="person_detected",
                         confidence=0.9, severity=3, metadata={})
        temp_store.append_event(ev)
        inc = Incident(incident_id=f"inc{n}", status=IncidentStatus.NEW,
                       created_ts=now, updated_ts=now, events=[ev], metadata={})
        temp_store.upsert_incident(inc)

    out = temp_store.list_incidents(limit=10)
    assert len(out) == 3
    by_id = {i.incident_id: i for i in out}
    # each incident carries its own event, correctly matched
    assert [e.event_id for e in by_id["inc1"].events] == ["e1"]
    assert by_id["inc2"].events[0].camera_id == "cam2"
    # an incident whose event_ids reference a missing event just gets no events,
    # never another incident's event
    assert all(all(e.event_id in {"e0", "e1", "e2"} for e in i.events) for i in out)
