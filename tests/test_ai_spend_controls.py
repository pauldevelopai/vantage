"""
Owner spend controls (Costs page) + distinct-vehicle summary — pinned.

The three dials must validate (an unknown model can't be selected), the paid
throttle must cap per camera but never block a hotlist/watchlist frame, and
entity_summary must answer "how many of those sightings are the same vehicle".
"""

from datetime import datetime, timedelta

import pytest

from alibi import ai_config as ac
from alibi.cameras import frame_analyzer as fa
from alibi.cameras.cross_camera import CrossCameraTracker


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "CONFIG_FILE", tmp_path / "ai_config.json")


def test_defaults_and_roundtrip(isolated_config):
    cfg = ac.get_ai_config()
    assert cfg["vision_model"] == "claude-opus-4-8"
    assert cfg["paid_min_gap_seconds"] == 60
    assert cfg["narrate_vehicles"] is True

    ac.set_ai_config(vision_model="claude-haiku-4-5", paid_min_gap_seconds=120,
                     narrate_vehicles=False)
    cfg = ac.get_ai_config()
    assert cfg["vision_model"] == "claude-haiku-4-5"
    assert cfg["paid_min_gap_seconds"] == 120
    assert cfg["narrate_vehicles"] is False


def test_unknown_model_rejected(isolated_config):
    with pytest.raises(ValueError):
        ac.set_ai_config(vision_model="gpt-9")
    with pytest.raises(ValueError):
        ac.set_ai_config(paid_min_gap_seconds=7)


def test_hand_edited_junk_model_falls_back(isolated_config):
    ac.CONFIG_FILE.write_text('{"vision_model": "made-up"}')
    assert ac.get_ai_config()["vision_model"] == "claude-opus-4-8"


def test_paid_throttle_caps_per_camera_but_flagged_always_pays():
    fa._last_paid.clear()
    assert fa.should_pay("camA", 1000.0, 60) is True
    assert fa.should_pay("camA", 1030.0, 60) is False      # inside the gap
    assert fa.should_pay("camB", 1030.0, 60) is True       # other camera unaffected
    assert fa.should_pay("camA", 1035.0, 60, flagged=True) is True  # hotlist/watchlist
    assert fa.should_pay("camA", 1061.0, 60) is False      # flagged call reset the clock
    assert fa.should_pay("camA", 1100.0, 60) is True


def test_entity_summary_counts_the_same_vehicle(tmp_path):
    t = CrossCameraTracker(storage_path=str(tmp_path / "cc.jsonl"), retention_hours=48)
    now = datetime.now()
    # the same vehicle (one embedding direction) seen 3x, another once
    import numpy as np
    rng = np.random.default_rng(3)
    suv = rng.standard_normal(128).astype(np.float32)
    other = -suv                                     # maximally dissimilar
    for i, dt in enumerate((5, 3, 1)):
        t.record_appearance_sighting("dahua-91", "vehicle", suv,
                                     (now - timedelta(hours=dt)).isoformat(),
                                     id_prefix="vehicle")
    t.record_appearance_sighting("dahua-92", "vehicle", other,
                                 (now - timedelta(hours=2)).isoformat(),
                                 id_prefix="vehicle")

    summary = t.entity_summary("vehicle", hours=24)
    assert len(summary) == 2                         # two DISTINCT vehicles
    assert summary[0]["count"] == 3                  # most-seen first
    assert summary[0]["cameras"] == ["dahua-91"]
    assert summary[1]["count"] == 1
    assert sum(summary[0]["hours"]) == 3


# ── narration trigger policy ───────────────────────────────────────────────

from alibi.ai_config import narration_allowed, DEFAULTS


def _cfg(**kw):
    cfg = dict(DEFAULTS)
    cfg.update(kw)
    return cfg


def test_flagged_always_narrates_even_over_budget_at_noon():
    cfg = _cfg(schedule="night", daily_budget_usd=1.0, narrate_people=False)
    assert narration_allowed(cfg, False, False, True, 12 * 60, 99.0) is True


def test_subject_toggles():
    assert narration_allowed(_cfg(narrate_people=False), True, False, False, 600, 0) is False
    assert narration_allowed(_cfg(narrate_vehicles=False), False, True, False, 600, 0) is False
    assert narration_allowed(_cfg(), True, False, False, 600, 0) is True


def test_daily_budget_hard_stop():
    cfg = _cfg(daily_budget_usd=2.0)
    assert narration_allowed(cfg, True, False, False, 600, 1.99) is True
    assert narration_allowed(cfg, True, False, False, 600, 2.0) is False
    assert narration_allowed(_cfg(daily_budget_usd=0), True, False, False, 600, 500.0) is True


def test_night_schedule_window():
    cfg = _cfg(schedule="night")
    assert narration_allowed(cfg, True, False, False, 23 * 60, 0) is True    # 23:00
    assert narration_allowed(cfg, True, False, False, 3 * 60, 0) is True     # 03:00
    assert narration_allowed(cfg, True, False, False, 12 * 60, 0) is False   # noon


def test_after_hours_uses_site_hours_with_night_fallback():
    cfg = _cfg(schedule="after_hours")
    hours = {"open": "06:00", "close": "22:00"}
    assert narration_allowed(cfg, True, False, False, 23 * 60, 0, normal_hours=hours) is True
    assert narration_allowed(cfg, True, False, False, 12 * 60, 0, normal_hours=hours) is False
    # no hours set -> falls back to the 22:00-06:00 night window
    assert narration_allowed(cfg, True, False, False, 23 * 60, 0, normal_hours=None) is True


def test_config_roundtrip_new_fields(isolated_config):
    ac.set_ai_config(schedule="night", daily_budget_usd=3.5, narrate_people=False)
    cfg = ac.get_ai_config()
    assert (cfg["schedule"], cfg["daily_budget_usd"], cfg["narrate_people"]) == ("night", 3.5, False)
    with pytest.raises(ValueError):
        ac.set_ai_config(schedule="sometimes")
