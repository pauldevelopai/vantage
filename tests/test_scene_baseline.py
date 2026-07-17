"""
Per-camera scene baseline, pinned against the two real scenes that motivated it:

  camera .91 — a white SUV genuinely parked in the driveway (car @ 0.794)
  camera .92 — shrubs the detector calls a car (car @ 0.6-0.7)

Both are "vehicle = 1" forever. No confidence threshold separates them (0.794 vs
0.7). Persistence does: both are always there, so neither is news.
"""

from alibi.cameras.scene_baseline import SceneBaseline


def _bl(**kw):
    # In-memory only — never touch disk in tests.
    store = {}
    return SceneBaseline(storage_path=None, loader=lambda: store,
                         saver=lambda h: store.update(h), min_frames=8, **kw)


def _teach(bl, cam, comp, n):
    for _ in range(n):
        bl.observe(cam, comp)


# --- the parked SUV (real) and the shrub (false) both go quiet -------------- #

def test_the_parked_suv_becomes_scenery():
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1, "person": 0}, 20)
    news, why = bl.newsworthy("cam-91", {"vehicle": 1, "person": 0})
    assert news is False
    assert "always shows" in why


def test_the_shrub_that_looks_like_a_car_becomes_scenery():
    # Identical treatment — we never have to know it's a shrub.
    bl = _bl()
    _teach(bl, "cam-92", {"vehicle": 1, "person": 0}, 20)
    assert bl.newsworthy("cam-92", {"vehicle": 1, "person": 0})[0] is False


def test_flicker_does_not_defeat_the_baseline():
    """The failure that beat the change-vs-last-frame rule: detection flickers
    1 -> 0 -> 1, and every 0->1 looked like an arrival."""
    bl = _bl()
    for i in range(24):
        bl.observe("cam-92", {"vehicle": 1 if i % 3 else 0})   # mostly 1, sometimes 0
    assert bl.newsworthy("cam-92", {"vehicle": 1})[0] is False  # still just the shrub


# --- but real events still get through ------------------------------------- #

def test_a_person_by_the_parked_car_is_still_news():
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1, "person": 0}, 20)
    news, why = bl.newsworthy("cam-91", {"vehicle": 1, "person": 1})
    assert news is True
    assert "person" in why and "normally shows none" in why


def test_a_second_vehicle_beside_the_parked_one_is_news():
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1, "person": 0}, 20)
    news, why = bl.newsworthy("cam-91", {"vehicle": 2, "person": 0})
    assert news is True
    assert "more than the usual 1" in why


def test_one_visitor_does_not_teach_the_camera_that_visitors_are_normal():
    # The median is robust: a few odd frames must not move "normal".
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1, "person": 0}, 20)
    _teach(bl, "cam-91", {"vehicle": 1, "person": 1}, 3)        # someone visits
    assert bl.normal("cam-91")["person"] == 0                   # still abnormal
    assert bl.newsworthy("cam-91", {"vehicle": 1, "person": 1})[0] is True


def test_flagged_is_never_scenery():
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1}, 20)
    assert bl.newsworthy("cam-91", {"vehicle": 1}, flagged=True)[0] is True


def test_empty_scene_is_not_news():
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1}, 20)
    assert bl.newsworthy("cam-91", {"vehicle": 0, "person": 0})[0] is False


# --- learning behaviour ----------------------------------------------------- #

def test_while_learning_everything_present_is_news_and_says_so():
    bl = _bl()
    news, why = bl.newsworthy("new-cam", {"vehicle": 1})
    assert news is True
    assert "still learning" in why


def test_normal_is_the_median_per_class():
    bl = _bl()
    for v in [1, 1, 1, 1, 5, 1, 1, 1, 1, 1]:
        bl.observe("c", {"vehicle": v})
    assert bl.normal("c")["vehicle"] == 1        # the 5 doesn't drag it


def test_window_forgets_old_scenes():
    bl = _bl(window=10)
    _teach(bl, "c", {"vehicle": 3}, 10)          # old normal
    _teach(bl, "c", {"vehicle": 0}, 10)          # the car left for good
    assert bl.normal("c")["vehicle"] == 0
    assert bl.newsworthy("c", {"vehicle": 1})[0] is True   # now a car IS news


def test_baselines_are_per_camera():
    bl = _bl()
    _teach(bl, "cam-91", {"vehicle": 1}, 20)
    _teach(bl, "cam-99", {"vehicle": 0}, 20)
    assert bl.newsworthy("cam-91", {"vehicle": 1})[0] is False   # SUV camera: normal
    assert bl.newsworthy("cam-99", {"vehicle": 1})[0] is True    # clean camera: news


def test_malformed_input_does_not_crash():
    bl = _bl()
    bl.observe("c", {"vehicle": "x", "person": None})
    bl.observe("c", None)
    assert bl.newsworthy("c", {})[0] is False


def test_reasons_are_readable_english():
    # These strings are shown to the owner and quoted in the brief.
    bl = _bl()
    _teach(bl, "c", {"vehicle": 1}, 20)
    assert "2 vehicles — more than the usual 1" in bl.newsworthy("c", {"vehicle": 2})[1]
    _teach(bl, "d", {"vehicle": 2}, 20)
    assert "3 vehicles — more than the usual 2" in bl.newsworthy("d", {"vehicle": 3})[1]
