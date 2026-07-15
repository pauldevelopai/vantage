"""
Tests for the Vantage site profile — WHAT a deployment protects and how the
intelligence layer is tailored to it (home / office / neighbourhood).

Covers: the three built-in postures and their safety posture (situational, never
accusatory), subject-type normalization, and the JSON-backed CRUD store.
"""

import pytest

from alibi.site_profile import (
    POSTURES,
    SUBJECT_TYPES,
    SiteProfileStore,
    normalize_subject_type,
    posture_for,
)


@pytest.fixture
def store(tmp_path):
    return SiteProfileStore(storage_path=str(tmp_path / "site_profiles.json"))


# --- postures -------------------------------------------------------------- #

def test_three_postures_exist():
    assert set(POSTURES) == set(SUBJECT_TYPES) == {"home", "office", "neighbourhood"}
    for st, p in POSTURES.items():
        assert p.subject_type == st
        assert p.focus and p.normal and p.review_triggers and p.brief_sections


def test_postures_are_situational_not_accusatory():
    """A trigger names a situation ('presence at the perimeter'), never a person
    or an accusation ('intruder', 'suspect', 'criminal')."""
    banned = ("intruder", "suspect", "criminal", "burglar", "thief", "perpetrator")
    for p in POSTURES.values():
        for trigger in p.review_triggers:
            low = trigger.lower()
            assert not any(b in low for b in banned), f"{p.subject_type}: {trigger}"


def test_postures_differ_by_type():
    # The whole point: each subject type weights different things.
    assert POSTURES["home"].focus != POSTURES["office"].focus
    assert "cross-property" in " ".join(POSTURES["neighbourhood"].brief_sections)
    assert "loading" in " ".join(POSTURES["office"].focus).lower()
    assert "perimeter" in " ".join(POSTURES["home"].focus).lower()


def test_normalize_subject_type():
    assert normalize_subject_type("home") == "home"
    assert normalize_subject_type("House") == "home"
    assert normalize_subject_type("business") == "office"
    assert normalize_subject_type("estate") == "neighbourhood"
    assert normalize_subject_type("") == "home"          # tolerant default
    assert normalize_subject_type(None) == "home"
    assert normalize_subject_type("weird-thing") == "home"


def test_posture_for_never_raises():
    assert posture_for("office").subject_type == "office"
    assert posture_for("nonsense").subject_type == "home"


# --- store CRUD ------------------------------------------------------------ #

def test_create_and_get(store):
    s = store.create(name="My House", subject_type="home", area="Parkview")
    assert s.site_id.startswith("site_")
    assert s.subject_type == "home"
    assert s.area == "Parkview"
    assert store.get(s.site_id) == s
    assert s.posture().subject_type == "home"


def test_create_normalizes_subject_type(store):
    s = store.create(name="Shop", subject_type="business")
    assert s.subject_type == "office"


def test_list_is_stable(store):
    a = store.create(name="A", subject_type="home")
    b = store.create(name="B", subject_type="office")
    ids = [s.site_id for s in store.list()]
    assert ids == [a.site_id, b.site_id]


def test_update(store):
    s = store.create(name="Site", subject_type="home", area="Old")
    updated = store.update(s.site_id, area="New", subject_type="neighbourhood",
                           camera_ids=["cam1", "cam2"])
    assert updated.area == "New"
    assert updated.subject_type == "neighbourhood"
    assert updated.camera_ids == ["cam1", "cam2"]
    assert updated.updated_at >= updated.created_at


def test_update_ignores_unknown_and_none(store):
    s = store.create(name="Site", subject_type="home", area="Keep")
    store.update(s.site_id, area=None, bogus="x")   # both ignored
    assert store.get(s.site_id).area == "Keep"


def test_update_unknown_site_returns_none(store):
    assert store.update("site_nope", name="x") is None


def test_delete(store):
    s = store.create(name="Site", subject_type="home")
    assert store.delete(s.site_id) is True
    assert store.get(s.site_id) is None
    assert store.delete(s.site_id) is False


def test_posture_lookup_by_site(store):
    s = store.create(name="Office", subject_type="office")
    assert store.posture(s.site_id).subject_type == "office"
    assert store.posture("site_nope") is None


# --- persistence ----------------------------------------------------------- #

def test_survives_reload(tmp_path):
    path = str(tmp_path / "site_profiles.json")
    r1 = SiteProfileStore(storage_path=path)
    s = r1.create(name="Persisted", subject_type="office", area="CBD",
                  normal_hours={"open": "07:00", "close": "18:00"})

    r2 = SiteProfileStore(storage_path=path)   # fresh load from disk
    got = r2.get(s.site_id)
    assert got is not None
    assert got.name == "Persisted"
    assert got.subject_type == "office"
    assert got.normal_hours == {"open": "07:00", "close": "18:00"}


def test_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "site_profiles.json"
    path.write_text("{not valid json")
    store = SiteProfileStore(storage_path=str(path))   # must not raise
    assert store.list() == []
