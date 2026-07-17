"""
Familiar vs new + explicit pattern findings + security suggestions — pinned.

The classification is what stops "your own car in your drive" being treated
like a stranger; the findings must say explicitly what's happening; the
suggestions must come from real observed gaps and honestly disappear when
there is no gap.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from alibi.patterns import familiarity as fam
from alibi.patterns.suggestions import security_suggestions

NOW = datetime(2026, 7, 17, 12, 0, 0)


@pytest.fixture
def isolated_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(fam, "LABELS_FILE", tmp_path / "vehicle_labels.json")


# ── classify_entity ────────────────────────────────────────────────────────

def test_own_parked_car_is_resident():
    # seen across 4 days and 12 different hours of the day — it IS the scene
    cls = fam.classify_entity(1500, (NOW - timedelta(days=4)).isoformat(),
                              NOW.isoformat(), days=4, active_hours=12, now=NOW)
    assert cls == "resident"


def test_first_sighting_today_is_new():
    cls = fam.classify_entity(3, (NOW - timedelta(hours=2)).isoformat(),
                              NOW.isoformat(), days=1, active_hours=1, now=NOW)
    assert cls == "new"


def test_daily_visitor_with_rhythm_is_regular():
    # 3 days but concentrated in 2 hours of the day (school run) -> regular
    cls = fam.classify_entity(9, (NOW - timedelta(days=3)).isoformat(),
                              NOW.isoformat(), days=3, active_hours=2, now=NOW)
    assert cls == "regular"


def test_one_old_sighting_is_occasional():
    cls = fam.classify_entity(1, (NOW - timedelta(days=5)).isoformat(),
                              (NOW - timedelta(days=5)).isoformat(),
                              days=1, active_hours=1, now=NOW)
    assert cls == "occasional"


# ── owner labels ───────────────────────────────────────────────────────────

def test_label_roundtrip_and_removal(isolated_labels):
    fam.set_vehicle_label("vehicle_1", "Paul's Fortuner", set_by="admin", now=NOW)
    assert fam.get_vehicle_labels()["vehicle_1"]["label"] == "Paul's Fortuner"
    fam.set_vehicle_label("vehicle_1", "", set_by="admin", now=NOW)
    assert "vehicle_1" not in fam.get_vehicle_labels()


# ── pattern findings ───────────────────────────────────────────────────────

def _entity(eid, label, count, first_days_ago, days, active_hours, hours=None):
    return {"entity_id": eid, "label": label, "count": count,
            "first_seen": (NOW - timedelta(days=first_days_ago)).isoformat(),
            "last_seen": NOW.isoformat(), "days": days, "active_hours": active_hours,
            "busiest_hour_utc": 6, "cameras": ["Driveway"], "hours": hours or [0] * 24}


def test_findings_new_first_and_explicit(isolated_labels):
    rows = fam.pattern_findings(
        [_entity("v1", "Vehicle A", 1500, 4, 4, 12),
         _entity("v2", "Vehicle B", 3, 0.1, 1, 1)],
        labels={"v1": {"label": "Paul's Fortuner"}},
        camera_normals={"Driveway": {"vehicle": 1, "person": 0}},
        people_by_hour=None, now=NOW)
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "new"                          # new arrivals lead
    assert "NEW to the scene" in rows[0]["text"]
    resident = next(r for r in rows if r["kind"] == "resident")
    assert "Paul's Fortuner" in resident["text"]      # the owner's name is used
    assert "part of the scene" in resident["text"]
    scene = next(r for r in rows if r["kind"] == "scene")
    assert "normally shows 1 vehicle" in scene["text"]


def test_unnamed_resident_prompts_naming(isolated_labels):
    rows = fam.pattern_findings([_entity("v1", "Vehicle A", 900, 5, 5, 10)],
                                labels={}, now=NOW)
    resident = next(r for r in rows if r["kind"] == "resident")
    assert "name it" in resident["text"]


# ── security suggestions ───────────────────────────────────────────────────

def _site(hours=None):
    return SimpleNamespace(name="My House", normal_hours=hours or {})


def test_suggestions_from_real_gaps():
    out = security_suggestions(
        sites=[_site()], cameras=[SimpleNamespace(name="Driveway", status="online", enabled=True)],
        enrolled_faces=0, face_sightings_ever=0, person_events_window=7,
        hotlist_count=0, cameras_with_area=0)
    titles = [s["title"] for s in out]
    assert "Set your normal hours" in titles
    assert "Enrol the people who belong here" in titles
    assert "No camera catches faces" in titles
    assert "Add plates to your hotlist" in titles
    assert "Set your cameras' area" in titles
    # every suggestion cites its evidence and links somewhere actionable
    assert all(s["why"] and s["link"].startswith("/") for s in out)


def test_no_gaps_no_suggestions():
    out = security_suggestions(
        sites=[_site({"open": "06:00", "close": "22:00"})],
        cameras=[SimpleNamespace(name="Driveway", status="online", enabled=True, area="Obs")],
        enrolled_faces=2, face_sightings_ever=10, person_events_window=7,
        hotlist_count=3, cameras_with_area=1)
    assert out == []                                   # honestly empty, never filler


# ── vehicle reference validation ───────────────────────────────────────────

from alibi.dataengine.vehicle_reference import validate_vehicle_attrs


def test_unknown_make_downgraded_known_kept():
    makes = {"toyota", "ford"}
    out = validate_vehicle_attrs([
        {"make": "Toyota", "model": "Fortuner", "confidence": "high"},
        {"make": "Zorblax", "model": "Z9", "confidence": "high"},
        {"make": None, "model": None, "confidence": "low"},
    ], makes=makes)
    assert out[0]["confidence"] == "high"
    assert out[1]["confidence"] == "low" and "catalog" in out[1]["downgraded"]
    assert out[2]["confidence"] == "low"


def test_empty_catalog_changes_nothing():
    rows = [{"make": "Zorblax", "model": "Z9", "confidence": "high"}]
    assert validate_vehicle_attrs(rows, makes=set()) == rows
