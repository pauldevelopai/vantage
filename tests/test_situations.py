"""
Situations engine — out-of-ordinary vehicles + unified ranking (pinned).

The usual cars must be excluded (that's what "out of the ordinary" means), the
ranking must put a human confirmation above a live criteria signal above a
routine note, and nothing here may promote a machine signal to "confirmed".
"""

from datetime import datetime, timedelta

from alibi.patterns.situations import (
    out_of_ordinary_vehicles, new_vehicle_situations, rank_situations, priority_of,
)

NOW = datetime(2026, 7, 20, 12, 0, 0)


def _entity(eid, count, first_days_ago, days, active_hours, busiest_hour=8, cams=None):
    hours = [0] * 24
    hours[busiest_hour] = count
    return {"entity_id": eid, "count": count,
            "first_seen": (NOW - timedelta(days=first_days_ago)).isoformat(),
            "last_seen": NOW.isoformat(), "days": days, "active_hours": active_hours,
            "hours": hours, "cameras": cams or ["cam-a"]}


# ── out_of_ordinary_vehicles ────────────────────────────────────────────────

def test_residents_and_regulars_are_excluded():
    ent = [
        _entity("v_res", 1500, 5, 5, 12),      # resident (own car)
        _entity("v_reg", 40, 4, 3, 2),         # regular (rhythm)
        _entity("v_new", 3, 0.1, 1, 1),        # new to the scene
        _entity("v_occ", 2, 6, 1, 1),          # occasional
    ]
    out = out_of_ordinary_vehicles(ent, now=NOW)
    ids = [r["entity_id"] for r in out]
    assert "v_res" not in ids and "v_reg" not in ids       # the usual cars are gone
    assert ids[0] == "v_new"                               # new leads
    assert "v_occ" in ids


def test_owner_named_vehicle_is_never_out_of_ordinary():
    ent = [_entity("v_new", 3, 0.1, 1, 1)]
    out = out_of_ordinary_vehicles(ent, labels={"v_new": {"label": "Paul's Fortuner"}},
                                   now=NOW)
    assert out == []                                       # named = known = not flagged


def test_row_reports_how_often_and_when():
    out = out_of_ordinary_vehicles([_entity("v_new", 4, 0.1, 1, 1, busiest_hour=6)],
                                   now=NOW)
    assert out[0]["count"] == 4                            # how often it came down the road
    assert out[0]["busiest_hour_local"] == 8              # 06:00 UTC + 2h = 08:00 local


def test_camera_ids_are_display_named():
    out = out_of_ordinary_vehicles([_entity("v_new", 2, 0.1, 1, 1, cams=["cam-a"])],
                                   names={"cam-a": "Driveway"}, now=NOW)
    assert out[0]["cameras"] == ["Driveway"]


# ── new_vehicle_situations ──────────────────────────────────────────────────

def test_new_vehicle_becomes_a_worth_a_look_situation():
    ooo = out_of_ordinary_vehicles([_entity("v_new", 3, 0.1, 1, 1)], now=NOW)
    sits = new_vehicle_situations(ooo)
    assert len(sits) == 1
    s = sits[0]
    assert s["kind"] == "new_vehicle" and s["tier"] == "review"
    assert s["entity_id"] == "v_new"
    assert "worth a look" in s["description"].lower()
    assert s["confirmed"] is None                          # never machine-confirmed


def test_occasional_vehicle_is_not_a_standalone_situation():
    ooo = out_of_ordinary_vehicles([_entity("v_occ", 2, 6, 1, 1)], now=NOW)
    assert new_vehicle_situations(ooo) == []               # only 'new' gets its own card


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
