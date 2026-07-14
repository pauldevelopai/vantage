"""Tests for Phase 2 co-occurrence ('vehicle near N incidents')."""

from datetime import datetime, timedelta

from alibi.schemas import Incident, CameraEvent, IncidentStatus
from alibi.patterns.co_occurrence import find_incidents_near, CoOccurrence


T = datetime(2026, 7, 12, 10, 0, 0)


def _event(cam, ts):
    return CameraEvent(
        event_id="e", camera_id=cam, ts=ts, zone_id="z",
        event_type="person_detected", confidence=0.8, severity=3,
    )


def _incident(iid, cam, ts):
    return Incident(
        incident_id=iid, status=IncidentStatus.NEW,
        created_ts=ts, updated_ts=ts, events=[_event(cam, ts)],
    )


def test_hit_when_same_camera_within_window():
    sightings = [("cam_a", T)]
    incidents = [
        _incident("near", "cam_a", T + timedelta(minutes=10)),   # same cam, +10m -> hit
        _incident("far_cam", "cam_b", T + timedelta(minutes=5)), # different cam -> no
        _incident("far_time", "cam_a", T + timedelta(hours=2)),  # same cam, +2h -> no
    ]
    hits = find_incidents_near(sightings, incidents, window_minutes=30)
    assert [h.incident_id for h in hits] == ["near"]
    assert hits[0].camera_id == "cam_a"
    assert hits[0].gap_seconds == 600.0


def test_one_hit_per_incident():
    # two sightings both near the same incident -> still one hit
    sightings = [("cam_a", T), ("cam_a", T + timedelta(minutes=1))]
    incidents = [_incident("inc", "cam_a", T + timedelta(minutes=2))]
    hits = find_incidents_near(sightings, incidents, window_minutes=30)
    assert len(hits) == 1


def test_no_incidents_nearby():
    hits = find_incidents_near([("cam_x", T)], [_incident("i", "cam_y", T)], 30)
    assert hits == []


class _FakeStore:
    def __init__(self, incidents):
        self._incidents = incidents

    def list_incidents(self, limit=500):
        return self._incidents[:limit]


def test_entity_incidents_summary():
    incidents = [
        _incident("i1", "cam_a", T + timedelta(minutes=5)),
        _incident("i2", "cam_a", T + timedelta(minutes=20)),
    ]
    co = CoOccurrence(incident_store=_FakeStore(incidents))
    res = co.entity_incidents([("cam_a", T)], window_minutes=30, entity_label="plate N123W")
    assert res.incident_count == 2
    assert "near 2 incident" in res.summary
    assert "plate N123W" in res.summary


def test_plate_incidents_pulls_vehicle_sightings(tmp_path):
    from alibi.vehicles.sightings_store import VehicleSightingsStore, VehicleSighting
    vs = VehicleSightingsStore(storage_path=str(tmp_path / "veh.jsonl"))
    vs.add_sighting(VehicleSighting(
        sighting_id="v1", camera_id="cam_a", ts=T.isoformat(), bbox=(0, 0, 5, 5),
        color="white", make="unknown", model="unknown", confidence=0.8,
        metadata={"plate_text": "N123W"}))

    incidents = [_incident("i1", "cam_a", T + timedelta(minutes=10))]
    co = CoOccurrence(incident_store=_FakeStore(incidents))
    res = co.plate_incidents("N123W", vehicle_store=vs, window_minutes=30)
    assert res.incident_count == 1
    assert "plate N123W" in res.entity_label
