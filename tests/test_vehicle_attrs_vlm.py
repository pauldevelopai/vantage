"""
VLM vehicle attributes — the honesty rules, pinned.

The classifier is a stub, so the ONLY lawful sources of make/model are the
VLM's structured answer about the image, or nothing. These tests pin:
  * parse_vehicle_attrs never invents a field (null / "unknown" -> absent),
  * record_vehicle_sightings attaches attributes only when the pairing is
    unambiguous (one vehicle detected, one described), and
  * unparseable model output degrades to a clean description + no vehicles.
"""

from datetime import datetime

from alibi.vision.scene_analyzer import parse_vehicle_attrs
from alibi.cameras.frame_analyzer import record_vehicle_sightings


# ── parse_vehicle_attrs ────────────────────────────────────────────────────

def test_parse_splits_description_and_vehicles():
    text = ('A white SUV with roof rails is parked on a cobblestone driveway.\n'
            '{"vehicles": [{"colour": "white", "make": "Toyota", "model": "Fortuner", '
            '"body": "SUV", "confidence": "high"}]}')
    desc, vehicles = parse_vehicle_attrs(text)
    assert desc == "A white SUV with roof rails is parked on a cobblestone driveway."
    assert vehicles == [{"colour": "white", "make": "Toyota", "model": "Fortuner",
                         "body": "SUV", "confidence": "high"}]


def test_parse_null_and_placeholder_fields_become_absent():
    text = ('A light vehicle at night.\n'
            '{"vehicles": [{"colour": "white", "make": null, "model": "unknown", '
            '"body": "N/A", "confidence": "low"}]}')
    _, vehicles = parse_vehicle_attrs(text)
    assert vehicles == [{"colour": "white", "make": None, "model": None,
                         "body": None, "confidence": "low"}]


def test_parse_no_json_means_no_vehicles():
    desc, vehicles = parse_vehicle_attrs("An empty driveway, no vehicles visible.")
    assert desc == "An empty driveway, no vehicles visible."
    assert vehicles == []


def test_parse_broken_json_keeps_description():
    text = 'A car near the gate. {"vehicles": [{"colour": "wh'
    desc, vehicles = parse_vehicle_attrs(text)
    assert vehicles == []
    assert "A car near the gate." in desc


def test_parse_bogus_confidence_downgraded_to_low():
    text = '{"vehicles": [{"colour": "red", "make": "BMW", "model": "X5", "body": "SUV", "confidence": "definitely"}]}'
    _, vehicles = parse_vehicle_attrs(text)
    assert vehicles[0]["confidence"] == "low"


# ── record_vehicle_sightings ───────────────────────────────────────────────

class FakeSightingsStore:
    def __init__(self):
        self.rows = []

    def add_sighting(self, s):
        self.rows.append(s)


NOW = datetime(2026, 7, 17, 10, 0, 0)


def test_attrs_attached_only_when_one_to_one():
    store = FakeSightingsStore()
    intel = {"detections": [{"class": "car", "confidence": 0.9, "bbox": [10, 10, 100, 80]}]}
    vehicles = [{"colour": "white", "make": "Toyota", "model": "Fortuner",
                 "body": "SUV", "confidence": "high"}]
    n = record_vehicle_sightings(intel, vehicles, "cam-1", NOW, "frameA", sightings_store=store)
    assert n == 1
    row = store.rows[0]
    assert (row.color, row.make, row.model) == ("white", "Toyota", "Fortuner")
    assert row.snapshot_url == "/api/cameras/frames/frameA.jpg"
    assert row.bbox == (10, 10, 100, 80)
    assert row.metadata["attr_source"] == "vlm"
    assert row.metadata["attr_confidence"] == "high"


def test_two_vehicles_one_description_attaches_nothing():
    """We can't know WHICH car the VLM described — guessing would stamp one
    car's attributes on another, so both rows stay unknown."""
    store = FakeSightingsStore()
    intel = {"detections": [
        {"class": "car", "confidence": 0.9, "bbox": [10, 10, 100, 80]},
        {"class": "truck", "confidence": 0.8, "bbox": [300, 50, 200, 150]},
    ]}
    vehicles = [{"colour": "white", "make": "Toyota", "model": "Fortuner",
                 "body": "SUV", "confidence": "high"}]
    n = record_vehicle_sightings(intel, vehicles, "cam-1", NOW, "frameB", sightings_store=store)
    assert n == 2
    for row in store.rows:
        assert (row.color, row.make, row.model) == ("unknown", "unknown", "unknown")
        assert "attr_source" not in row.metadata


def test_no_vlm_answer_stays_unknown():
    store = FakeSightingsStore()
    intel = {"detections": [{"class": "car", "confidence": 0.9, "bbox": [10, 10, 100, 80]}]}
    n = record_vehicle_sightings(intel, None, "cam-1", NOW, "frameC", sightings_store=store)
    assert n == 1
    assert (store.rows[0].make, store.rows[0].model) == ("unknown", "unknown")


def test_no_vehicle_detections_writes_nothing():
    store = FakeSightingsStore()
    intel = {"detections": [{"class": "person", "confidence": 0.95, "bbox": [5, 5, 30, 90]}]}
    assert record_vehicle_sightings(intel, [], "cam-1", NOW, "frameD", sightings_store=store) == 0
    assert store.rows == []
