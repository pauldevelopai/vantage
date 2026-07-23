"""
Situations engine — out-of-ordinary vehicles + unified ranking (pinned).

The usual cars must be excluded (that's what "out of the ordinary" means), the
ranking must put a human confirmation above a live criteria signal above a
routine note, and nothing here may promote a machine signal to "confirmed".
"""

from datetime import datetime, timedelta

from alibi.patterns.situations import (
    out_of_ordinary_vehicles, rank_situations, priority_of, visit_count, vehicle_descriptor,
)


# ── vehicle_descriptor (real description, never "Vehicle A") ─────────────────

def test_descriptor_prefers_owner_name():
    assert vehicle_descriptor("white", "SUV", owner_label="Paul's Fortuner") == "Paul's Fortuner"


def test_descriptor_from_colour_and_body():
    assert vehicle_descriptor("white", "SUV") == "White SUV"
    assert vehicle_descriptor("silver", None) == "Silver"
    assert vehicle_descriptor(None, "sedan") == "sedan"


def test_descriptor_none_when_nothing_known():
    # "unknown" colour + no body = no honest descriptor (caller shows the photo)
    assert vehicle_descriptor("unknown", None) is None
    assert vehicle_descriptor(None, None) is None

NOW = datetime(2026, 7, 20, 12, 0, 0)


def _entity(eid, count, first_days_ago, days, active_hours, busiest_hour=8, cams=None):
    hours = [0] * 24
    hours[busiest_hour] = count
    return {"entity_id": eid, "count": count,
            "first_seen": (NOW - timedelta(days=first_days_ago)).isoformat(),
            "last_seen": NOW.isoformat(), "days": days, "active_hours": active_hours,
            "hours": hours, "cameras": cams or ["cam-a"]}


# ── out_of_ordinary_vehicles ────────────────────────────────────────────────

def test_the_scene_is_excluded_even_within_one_day():
    # THE production bug: a car seen 1050×/day across 11 hours is the SCENE, not
    # out-of-ordinary — even though its ReID cluster is < 24h old.
    ent = [
        _entity("v_parked", 1050, 0.5, 1, 11),   # constant presence -> resident
        _entity("v_reg", 40, 4, 3, 2),           # regular (rhythm)
        _entity("v_new", 3, 0.1, 1, 1),          # a genuine new visitor
        _entity("v_occ", 2, 6, 1, 1),            # occasional visitor
    ]
    out = out_of_ordinary_vehicles(ent, now=NOW)
    ids = [r["entity_id"] for r in out]
    assert "v_parked" not in ids and "v_reg" not in ids    # the usual cars are gone
    assert ids[0] == "v_new"                               # new leads
    assert "v_occ" in ids


def test_high_sighting_count_alone_marks_the_scene():
    # active_hours below 6 but hundreds of sightings = still the scene, excluded
    out = out_of_ordinary_vehicles([_entity("v_busy", 335, 0.5, 1, 5)], now=NOW)
    assert out == []


def test_owner_named_vehicle_is_never_out_of_ordinary():
    ent = [_entity("v_new", 3, 0.1, 1, 1)]
    out = out_of_ordinary_vehicles(ent, labels={"v_new": {"label": "Paul's Fortuner"}},
                                   now=NOW)
    assert out == []                                       # named = known = not flagged


def test_row_reports_passes_not_sightings():
    out = out_of_ordinary_vehicles(
        [_entity("v_new", 12, 0.1, 1, 1, busiest_hour=6)],
        visits_by_entity={"v_new": 2}, now=NOW)
    assert out[0]["passes"] == 2                           # honest "how often": 2 visits
    assert out[0]["sightings"] == 12                       # raw stills kept, not shown as passes
    assert out[0]["busiest_hour_local"] == 8              # 06:00 UTC + 2h = 08:00 local


def test_camera_ids_are_display_named():
    out = out_of_ordinary_vehicles([_entity("v_new", 2, 0.1, 1, 1, cams=["cam-a"])],
                                   names={"cam-a": "Driveway"}, now=NOW)
    assert out[0]["cameras"] == ["Driveway"]


# ── visit_count (passes, not sightings) ─────────────────────────────────────

def test_parked_car_is_one_visit():
    # re-detected every minute for 10 minutes = ONE visit, not 11 sightings
    ts = [(NOW + timedelta(minutes=i)).isoformat() for i in range(11)]
    assert visit_count(ts) == 1


def test_two_separated_passes_count_as_two():
    ts = [NOW.isoformat(), (NOW + timedelta(minutes=1)).isoformat(),
          (NOW + timedelta(hours=3)).isoformat()]
    assert visit_count(ts) == 2


def test_no_timestamps_is_zero_visits():
    assert visit_count([]) == 0


# ── rank_situations ─────────────────────────────────────────────────────────

def test_ranking_confirmed_over_criteria_over_noted():
    rows = [
        {"kind": "noted", "ts": "2026-07-20T11:59:00"},
        {"kind": "new_vehicle", "ts": "2026-07-20T09:00:00"},
        {"kind": "confirmed", "ts": "2026-07-20T06:00:00"},
        {"kind": "after_hours", "ts": "2026-07-20T02:00:00"},
    ]
    ranked = rank_situations(rows, limit=5)
    assert [r["kind"] for r in ranked] == ["confirmed", "after_hours", "new_vehicle", "noted"]


def test_ranking_newest_first_within_a_tier():
    rows = [
        {"kind": "review", "ts": "2026-07-20T08:00:00"},
        {"kind": "review", "ts": "2026-07-20T11:00:00"},
    ]
    ranked = rank_situations(rows)
    assert [r["ts"] for r in ranked] == ["2026-07-20T11:00:00", "2026-07-20T08:00:00"]


def test_ranking_caps_to_limit():
    rows = [{"kind": "noted", "ts": f"2026-07-20T0{i}:00:00"} for i in range(9)]
    assert len(rank_situations(rows, limit=5)) == 5


def test_priority_order_is_sane():
    assert priority_of("confirmed") < priority_of("review") < priority_of("noted")
    assert priority_of("after_hours") < priority_of("new_vehicle") < priority_of("noted")


# ── ranked, numbered alerts (top ten by importance) ──────────────────────

def test_rank_alerts_numbers_and_orders_by_importance():
    from alibi.patterns.situations import rank_alerts
    rows = [
        {"kind": "noted", "tier": "noted", "event_type": "vehicle_detected",
         "owner_label": "My Toyota", "familiarity": "resident", "ts": "2026-07-20T10:00"},
        {"kind": "at_vehicles", "tier": "review", "ts": "2026-07-22T03:00"},
        {"kind": "noted", "tier": "noted", "event_type": "person_detected",
         "ts": "2026-07-22T14:00"},                      # unknown person
    ]
    ranked = rank_alerts(rows, limit=10)
    assert [r["rank"] for r in ranked] == [1, 2, 3]
    assert ranked[0]["kind"] == "at_vehicles"           # behaviour first
    assert ranked[-1]["owner_label"] == "My Toyota"     # named resident last


def test_a_hotlist_hit_outranks_ordinary_behaviour():
    from alibi.patterns.situations import rank_alerts
    ranked = rank_alerts([
        {"kind": "dwell", "tier": "review", "ts": "2026-07-22T05:00"},
        {"kind": "noted", "tier": "noted", "hotlist_hit": True, "ts": "2026-07-22T04:00"},
    ], limit=10)
    assert ranked[0]["hotlist_hit"] is True


def test_a_confirmed_incident_tops_everything():
    from alibi.patterns.situations import rank_alerts
    ranked = rank_alerts([
        {"kind": "at_vehicles", "tier": "review", "ts": "2026-07-22T05:00"},
        {"kind": "noted", "tier": "confirmed", "ts": "2026-07-22T01:00"},
    ], limit=10)
    assert ranked[0]["tier"] == "confirmed"


def test_rank_alerts_fills_up_to_ten_and_caps_there():
    from alibi.patterns.situations import rank_alerts
    rows = [{"kind": "noted", "tier": "noted", "ts": f"2026-07-22T{h:02d}:00"}
            for h in range(15)]
    ranked = rank_alerts(rows, limit=10)
    assert len(ranked) == 10
    assert [r["rank"] for r in ranked] == list(range(1, 11))
