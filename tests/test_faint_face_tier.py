"""
Faint faces may confirm someone you named — never invent someone new. Pinned.

Found live (2026-07-21): a woman in the driveway, looking down at her phone
under a high-mounted camera, produced a face SCRFD scored 0.481. The pipeline's
cutoff was 0.5, so the face was discarded before matching ever ran — meaning
enrolling her would have done nothing the next time she walked past.

The fix looks lower, but asymmetrically. A face under FACE_CONFIDENT is real
enough to CONFIRM an already-enrolled person on a stricter identity threshold,
and nothing else: no unknown-face sighting, no appearance cluster. The detector
fires on texture (a tree and paving have both been "faces" here), so looser
detection must never mean looser identity.
"""

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from alibi.vision import frame_intelligence as fi


class _Store:
    def __init__(self):
        self.sightings = []

    def add_sighting(self, s):
        self.sightings.append(s)


class _Tracker:
    def __init__(self):
        self.appearances = []
        self.sightings = []

    def record_appearance_sighting(self, **kw):
        self.appearances.append(kw)

    def record_sighting(self, **kw):
        self.sightings.append(kw)


def _mce(det_score, is_match, match_score):
    """A pipeline whose detector reports one face at `det_score`, and whose
    matcher answers `is_match` / `match_score` against the enrolled people."""
    entry = SimpleNamespace(person_id="lorraine-1", label="Lorraine")
    return SimpleNamespace(
        _face_detector=SimpleNamespace(
            detect_scored=lambda frame: [((420, 55, 24, 28), det_score)],
            extract_face=lambda frame, bbox: np.zeros((28, 24, 3), dtype=np.uint8),
        ),
        _face_embedder=SimpleNamespace(
            generate_embedding=lambda crop: np.ones(512, dtype=np.float32)),
        _watchlist_store=SimpleNamespace(
            get_all_embeddings=lambda: [np.ones(512, dtype=np.float32)],
            load_all=lambda: [entry]),
        _face_matcher=SimpleNamespace(
            match=lambda e, embs, labels: (is_match, [entry] if is_match else [], match_score)),
        _cross_camera_tracker=_Tracker(),
    )


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr("alibi.watchlist.face_sighting_store.get_face_sighting_store",
                        lambda: s)
    return s


def _run(mce, out=None):
    out = out if out is not None else {"faces": []}
    fi._run_faces(mce, np.zeros((524, 640, 3), dtype=np.uint8), "driveway",
                  datetime(2026, 7, 17, 15, 38, 43), out,
                  frame_id="bdf4afe5dee042e9", person_boxes=[(400, 50, 60, 180)])
    return out


def test_a_faint_face_matching_an_enrolled_person_is_recorded(store):
    """Lorraine's 0.481 face, once she's enrolled: this is the whole point."""
    mce = _mce(det_score=0.481, is_match=True, match_score=0.72)
    out = _run(mce)
    assert len(store.sightings) == 1
    assert store.sightings[0].matched_person_id == "lorraine-1"
    assert out["watchlist_label"] == "Lorraine"


def test_a_faint_face_matching_nobody_is_dropped_entirely(store):
    """A stranger's faint face — or a tree's — must leave no trace: no sighting
    to become an 'Unknown person' tile, no cluster to accrete more junk."""
    mce = _mce(det_score=0.42, is_match=False, match_score=0.1)
    _run(mce)
    assert store.sightings == []
    assert mce._cross_camera_tracker.appearances == []


def test_a_faint_face_needs_a_stricter_identity_score(store):
    """0.62 clears the everyday 0.6 bar but not the faint one — a weak face
    read is exactly where a confident-looking wrong match comes from."""
    assert 0.6 < 0.62 < fi.FAINT_MATCH_MIN
    mce = _mce(det_score=0.44, is_match=True, match_score=0.62)
    _run(mce)
    assert store.sightings == []


def test_a_confident_stranger_still_becomes_an_unknown_face(store):
    """Unchanged behaviour above the bar: clear faces still build the archive."""
    mce = _mce(det_score=0.87, is_match=False, match_score=0.1)
    _run(mce)
    assert len(store.sightings) == 1
    assert store.sightings[0].matched_person_id is None
    assert len(mce._cross_camera_tracker.appearances) == 1


def test_the_faint_tier_sits_below_the_confident_one():
    from alibi.watchlist import face_recover
    assert face_recover.RECOVER_THRESHOLD < fi.FACE_CONFIDENT
    assert fi.FAINT_MATCH_MIN > 0.6
