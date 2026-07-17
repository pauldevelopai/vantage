"""
Tests for Phase 2 person-history ("involved before?").

Seeds a temp face-sighting store with synthetic ArcFace-like embeddings and
verifies the look-up finds prior appearances, counts cameras, and surfaces a
watchlist match — without asserting identity.
"""

import numpy as np
import pytest

from alibi.watchlist.face_sighting_store import FaceSightingStore, FaceSighting
from alibi.patterns.person_history import PersonHistory


def _emb(base, noise, seed, dim=512):
    rng = np.random.default_rng(seed)
    v = base + noise * rng.standard_normal(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


@pytest.fixture
def store(tmp_path):
    return FaceSightingStore(storage_path=str(tmp_path / "face_sightings.jsonl"))


def _add(store, sid, cam, ts, emb, matched=None):
    store.add_sighting(FaceSighting(
        sighting_id=sid, camera_id=cam, ts=ts,
        embedding=emb.tolist(), bbox=(0, 0, 10, 10), confidence=0.9,
        matched_person_id=matched,
    ))


def test_no_prior_appearances(store):
    ph = PersonHistory(store=store)
    res = ph.look_up(_emb(None if False else np.zeros(512, np.float32) + 1, 0.0, 1))
    assert res.seen_before is False
    assert "No prior" in res.summary


def test_finds_prior_appearances_across_cameras(store):
    rng = np.random.default_rng(0)
    person = rng.standard_normal(512).astype(np.float32)
    # 3 prior sightings of the same person at 2 cameras
    _add(store, "s1", "cam_a", "2026-07-10T08:00:00", _emb(person, 0.05, 2))
    _add(store, "s2", "cam_b", "2026-07-11T09:00:00", _emb(person, 0.05, 3))
    _add(store, "s3", "cam_a", "2026-07-12T10:00:00", _emb(person, 0.05, 4))
    # an unrelated person
    _add(store, "s4", "cam_c", "2026-07-12T11:00:00", _emb(rng.standard_normal(512).astype(np.float32), 0.0, 5))

    ph = PersonHistory(match_threshold=0.5, store=store)
    res = ph.look_up(_emb(person, 0.05, 99))
    assert res.seen_before is True
    assert res.times_seen == 3
    assert sorted(res.distinct_cameras) == ["cam_a", "cam_b"]
    assert res.first_seen.startswith("2026-07-10")
    assert res.last_seen.startswith("2026-07-12")
    assert "prior appearance" in res.summary.lower()


def test_surfaces_watchlist_match(store):
    rng = np.random.default_rng(7)
    person = rng.standard_normal(512).astype(np.float32)
    _add(store, "s1", "cam_a", "2026-07-10T08:00:00", _emb(person, 0.05, 8), matched="person_007")

    ph = PersonHistory(store=store)
    res = ph.look_up(_emb(person, 0.05, 9))
    assert res.watchlist_person_id == "person_007"
    assert "person_007" in res.summary and "review" in res.summary.lower()


def test_excludes_current_sighting(store):
    rng = np.random.default_rng(11)
    person = rng.standard_normal(512).astype(np.float32)
    _add(store, "current", "cam_a", "2026-07-12T10:00:00", _emb(person, 0.02, 12))

    ph = PersonHistory(store=store)
    # excluding the only (current) sighting -> no priors
    res = ph.look_up(_emb(person, 0.02, 13), exclude_sighting_id="current")
    assert res.seen_before is False


# ── recent_people (the Overview people strip) ──────────────────────────────

from alibi.patterns.person_history import recent_people


def _add_full(store, sid, cam, ts, emb, matched=None, image_path="auto", bbox=(10, 20, 30, 40)):
    store.add_sighting(FaceSighting(
        sighting_id=sid, camera_id=cam, ts=ts,
        embedding=emb.tolist(), bbox=bbox, confidence=0.9,
        matched_person_id=matched,
        image_path=(f"/api/cameras/frames/{sid}.jpg" if image_path == "auto" else image_path),
    ))


def test_recent_people_empty_store(store):
    assert recent_people("2026-07-01T00:00:00", store=store) == []


def test_recent_people_dedupes_same_person_and_counts_continuity(store):
    rng = np.random.default_rng(21)
    visitor = rng.standard_normal(512).astype(np.float32)
    other = rng.standard_normal(512).astype(np.float32)
    # one visitor seen 3 times (a burst), another person once, all in-window
    _add_full(store, "v1", "cam_a", "2026-07-15T08:00:00", _emb(visitor, 0.05, 22))
    _add_full(store, "v2", "cam_a", "2026-07-16T09:00:00", _emb(visitor, 0.05, 23))
    _add_full(store, "v3", "cam_b", "2026-07-17T10:00:00", _emb(visitor, 0.05, 24))
    _add_full(store, "o1", "cam_a", "2026-07-17T11:00:00", _emb(other, 0.0, 25))

    rows = recent_people("2026-07-14T00:00:00", store=store)
    assert len(rows) == 2                        # one tile per person, not per frame
    assert rows[0]["sighting_id"] == "o1"        # newest first
    visitor_row = rows[1]
    assert visitor_row["sighting_id"] == "v3"    # the visitor's newest sighting
    assert visitor_row["times_seen"] == 3
    assert visitor_row["first_seen"].startswith("2026-07-15")
    assert visitor_row["matched_label"] is None  # stranger: continuity, no identity
    assert visitor_row["bbox"] == [10, 20, 30, 40]
    assert visitor_row["frame_url"].endswith("v3.jpg")


def test_recent_people_enrolled_gets_label_stranger_does_not(store):
    rng = np.random.default_rng(31)
    _add_full(store, "e1", "cam_a", "2026-07-17T08:00:00",
              _emb(rng.standard_normal(512).astype(np.float32), 0.0, 32), matched="p1")
    _add_full(store, "u1", "cam_a", "2026-07-17T09:00:00",
              _emb(rng.standard_normal(512).astype(np.float32), 0.0, 33))

    rows = recent_people("2026-07-14T00:00:00", store=store, labels={"p1": "Paul"})
    by_id = {r["sighting_id"]: r for r in rows}
    assert by_id["e1"]["matched_label"] == "Paul"
    assert by_id["u1"]["matched_label"] is None


def test_recent_people_window_and_frame_requirements(store):
    rng = np.random.default_rng(41)
    # out of window
    _add_full(store, "old", "cam_a", "2026-06-01T08:00:00",
              _emb(rng.standard_normal(512).astype(np.float32), 0.0, 42))
    # in window but no evidence frame -> cannot show a real crop -> not shown
    _add_full(store, "noframe", "cam_a", "2026-07-17T08:00:00",
              _emb(rng.standard_normal(512).astype(np.float32), 0.0, 43), image_path=None)

    assert recent_people("2026-07-14T00:00:00", store=store) == []


def test_recent_people_counts_history_beyond_window(store):
    rng = np.random.default_rng(51)
    person = rng.standard_normal(512).astype(np.float32)
    # prior appearance BEFORE the window still counts toward continuity
    _add_full(store, "past", "cam_a", "2026-06-01T08:00:00", _emb(person, 0.05, 52))
    _add_full(store, "now", "cam_a", "2026-07-17T08:00:00", _emb(person, 0.05, 53))

    rows = recent_people("2026-07-14T00:00:00", store=store)
    assert len(rows) == 1
    assert rows[0]["times_seen"] == 2
    assert rows[0]["first_seen"].startswith("2026-06-01")


def test_recent_people_read_time_watchlist_match(store):
    """Enrolment compounds immediately: a stranger's existing tile flips to the
    enrolled name via the read-time match (same conservative threshold)."""
    rng = np.random.default_rng(61)
    person = rng.standard_normal(512).astype(np.float32)
    _add_full(store, "s1", "cam_a", "2026-07-17T08:00:00", _emb(person, 0.02, 62))

    # not enrolled -> stranger
    rows = recent_people("2026-07-14T00:00:00", store=store)
    assert rows[0]["matched_label"] is None

    # enrolled (embedding from the sighting itself) -> named, no re-detection
    enrolled = _emb(person, 0.02, 63)
    rows = recent_people("2026-07-14T00:00:00", store=store,
                         labels={"p9": "Paul"},
                         watchlist_embeddings={"p9": enrolled.tolist()})
    assert rows[0]["matched_label"] == "Paul"

    # a DIFFERENT person stays a stranger even with enrolments present
    other = rng.standard_normal(512).astype(np.float32)
    _add_full(store, "s2", "cam_a", "2026-07-17T09:00:00", _emb(other, 0.0, 64))
    rows = recent_people("2026-07-14T00:00:00", store=store,
                         labels={"p9": "Paul"},
                         watchlist_embeddings={"p9": enrolled.tolist()})
    by_id = {r["sighting_id"]: r for r in rows}
    assert by_id["s2"]["matched_label"] is None
