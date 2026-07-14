"""Tests for Phase 2 windowed activity patterns."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from alibi.watchlist.face_sighting_store import FaceSightingStore, FaceSighting
from alibi.vehicles.sightings_store import VehicleSightingsStore, VehicleSighting
from alibi.patterns.activity_patterns import ActivityPatterns, parse_window


NOW = datetime(2026, 7, 12, 14, 0, 0)


def test_parse_window():
    assert parse_window("1h") == 1.0
    assert parse_window("24h") == 24.0
    assert parse_window("7d") == 168.0
    assert parse_window("week") == 168.0
    assert parse_window("30m") == 0.5
    assert parse_window("garbage") == 24.0


@pytest.fixture
def stores(tmp_path):
    fs = FaceSightingStore(storage_path=str(tmp_path / "faces.jsonl"))
    vs = VehicleSightingsStore(storage_path=str(tmp_path / "vehicles.jsonl"))
    return fs, vs


def _face(fs, sid, cam, ts, matched=None):
    fs.add_sighting(FaceSighting(
        sighting_id=sid, camera_id=cam, ts=ts,
        embedding=np.zeros(512, np.float32).tolist(), bbox=(0, 0, 5, 5),
        confidence=0.9, matched_person_id=matched))


def _veh(vs, sid, cam, ts, color="white", plate=None):
    vs.add_sighting(VehicleSighting(
        sighting_id=sid, camera_id=cam, ts=ts, bbox=(0, 0, 5, 5),
        color=color, make="unknown", model="unknown", confidence=0.8,
        metadata={"plate_text": plate} if plate else {}))


def test_windowed_counts_and_hotspot(stores):
    fs, vs = stores
    # within 24h
    _face(fs, "f1", "cam_a", (NOW - timedelta(hours=2)).isoformat())
    _face(fs, "f2", "cam_a", (NOW - timedelta(hours=3)).isoformat(), matched="person_X")
    _face(fs, "f3", "cam_b", (NOW - timedelta(hours=1)).isoformat())
    _veh(vs, "v1", "cam_a", (NOW - timedelta(hours=1)).isoformat(), color="red", plate="N123W")
    # outside 24h (should be excluded)
    _face(fs, "old", "cam_a", (NOW - timedelta(days=3)).isoformat())

    ap = ActivityPatterns(face_store=fs, vehicle_store=vs)
    s = ap.summarize("24h", now=NOW)

    assert s.people_sightings == 3           # 'old' excluded
    assert s.watchlist_matches == 1
    assert s.vehicle_sightings == 1
    assert s.plate_reads == 1
    assert s.busiest_camera == "cam_a"       # cam_a has 2 faces + 1 vehicle
    assert s.vehicle_colours.get("red") == 1
    assert "watchlist" in s.narrative.lower()


def test_empty_window(stores):
    fs, vs = stores
    ap = ActivityPatterns(face_store=fs, vehicle_store=vs)
    s = ap.summarize("1h", now=NOW)
    assert s.people_sightings == 0 and s.vehicle_sightings == 0
    assert "No activity" in s.narrative


def test_hour_window_excludes_older(stores):
    fs, vs = stores
    _face(fs, "recent", "cam_a", (NOW - timedelta(minutes=30)).isoformat())
    _face(fs, "older", "cam_a", (NOW - timedelta(hours=5)).isoformat())
    ap = ActivityPatterns(face_store=fs, vehicle_store=vs)
    s = ap.summarize("1h", now=NOW)
    assert s.people_sightings == 1           # only the 30-min-old one
