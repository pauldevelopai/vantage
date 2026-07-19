"""Field reports — validation, store roundtrip, corroboration. Honest data only."""

from datetime import datetime, timedelta

import pytest

from alibi.reports import field_reports as fr

NOW = datetime(2026, 7, 18, 2, 0, 0)


def test_build_report_normalises_and_keeps_supplied_tags():
    r = fr.build_report(observer="Guard Sipho", subject="Vehicle", note="  white bakkie at north gate  ",
                        camera_id="cam-a", tags={"colour": "White", "vehicle_type": "Bakkie",
                                                 "junk": ""}, now=NOW)
    assert r.subject == "vehicle"
    assert r.note == "white bakkie at north gate"
    assert r.tags == {"colour": "white", "vehicle_type": "bakkie"}   # empty dropped
    assert r.observer == "Guard Sipho"


def test_build_report_rejects_meaningless():
    with pytest.raises(ValueError):
        fr.build_report(observer="", subject="vehicle", note="x")
    with pytest.raises(ValueError):
        fr.build_report(observer="g", subject="vehicle", note="")
    with pytest.raises(ValueError):
        fr.build_report(observer="g", subject="alien", note="x")


def test_store_roundtrip_newest_first(tmp_path):
    store = fr.FieldReportStore(storage_path=str(tmp_path / "fr.jsonl"))
    store.add(fr.build_report("g", "person", "someone loitering", ts="2026-07-18T01:00:00", now=NOW))
    store.add(fr.build_report("g", "vehicle", "bakkie", ts="2026-07-18T02:00:00", now=NOW))
    out = store.list_recent()
    assert [r.subject for r in out] == ["vehicle", "person"]     # newest first
    assert out[0].note == "bakkie"


def test_corroboration_matches_same_camera_time_and_colour():
    report = fr.build_report("g", "vehicle", "white bakkie north gate", camera_id="cam-a",
                             tags={"colour": "white"}, ts=NOW.isoformat(), now=NOW)
    rows = [
        {"camera_id": "cam-b", "ts": NOW.isoformat(), "colour": "white", "event_id": "wrong-cam"},
        {"camera_id": "cam-a", "ts": (NOW + timedelta(minutes=5)).isoformat(),
         "colour": "white", "event_id": "match", "camera_name": "North Gate"},
    ]
    m = fr.corroborating_sighting(report, rows)
    assert m and m["event_id"] == "match"


def test_corroboration_none_when_colour_disagrees_or_out_of_window():
    report = fr.build_report("g", "vehicle", "white bakkie", camera_id="cam-a",
                             tags={"colour": "white"}, ts=NOW.isoformat(), now=NOW)
    assert fr.corroborating_sighting(report, [
        {"camera_id": "cam-a", "ts": NOW.isoformat(), "colour": "black", "event_id": "x"}]) is None
    assert fr.corroborating_sighting(report, [
        {"camera_id": "cam-a", "ts": (NOW + timedelta(hours=2)).isoformat(),
         "colour": "white", "event_id": "x"}]) is None


def test_corroboration_skipped_for_non_vehicle():
    report = fr.build_report("g", "person", "someone", camera_id="cam-a", ts=NOW.isoformat(), now=NOW)
    assert fr.corroborating_sighting(report, [{"camera_id": "cam-a", "ts": NOW.isoformat()}]) is None
