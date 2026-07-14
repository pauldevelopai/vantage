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
