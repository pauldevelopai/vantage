"""
Tests for appearance-based (ReID) cross-camera correlation.

These verify the capability upgrade: linking the SAME entity across cameras by
embedding similarity, where the old exact-string / MD5-hash approach could not.
They use synthetic embeddings, so no ReID model / torch is required.
"""

from datetime import datetime, timedelta
import hashlib

import numpy as np
import pytest

from alibi.cameras.cross_camera import CrossCameraTracker
from alibi.cameras.appearance_reid import cosine_similarity


def _tracker(tmp_path):
    return CrossCameraTracker(
        min_travel_seconds=300,
        reappearance_window_minutes=30,
        reappearance_camera_threshold=3,
        storage_path=str(tmp_path / "xcam.jsonl"),
        retention_hours=24,
    )


def _emb(base, noise=0.0, seed=0, dim=512):
    """A deterministic unit vector, optionally perturbed to simulate a second
    sighting of the same entity from another camera."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32) if base is None else base.copy()
    if noise:
        v = v + noise * rng.standard_normal(dim).astype(np.float32)
    return v


def test_same_entity_linked_across_cameras(tmp_path):
    """Near-identical embeddings at two cameras resolve to ONE entity id."""
    t = _tracker(tmp_path)
    base = _emb(None, seed=1)
    cam_a = _emb(base, noise=0.05, seed=2)   # camera A view
    cam_b = _emb(base, noise=0.05, seed=3)   # camera B view (same vehicle)

    # sanity: the two views are genuinely similar but NOT bit-identical
    assert cosine_similarity(cam_a, cam_b) > 0.9
    assert not np.array_equal(cam_a, cam_b)

    now = datetime.now()  # relative — cross-camera retention is 24h
    id_a, _ = t.record_appearance_sighting(
        "cam_a", "vehicle", cam_a, now.isoformat(), match_threshold=0.6)
    id_b, alerts = t.record_appearance_sighting(
        "cam_b", "vehicle", cam_b, (now + timedelta(seconds=30)).isoformat(),
        match_threshold=0.6)

    assert id_a == id_b, "same vehicle at two cameras must share one identity"
    # 30s between two cameras < 300s min travel -> impossible-travel alert
    assert any(a.alert_type == "impossible_travel" for a in alerts)


def test_old_hash_approach_would_fail(tmp_path):
    """Demonstrates why the upgrade matters: MD5-of-embedding never links two
    near-identical (non-identical) sightings."""
    base = _emb(None, seed=1)
    cam_a = _emb(base, noise=0.05, seed=2)
    cam_b = _emb(base, noise=0.05, seed=3)

    hash_a = hashlib.md5(cam_a.tobytes()).hexdigest()[:12]
    hash_b = hashlib.md5(cam_b.tobytes()).hexdigest()[:12]
    assert hash_a != hash_b  # old approach: treated as two different entities

    # new approach links them (covered by the test above)
    assert cosine_similarity(cam_a, cam_b) > 0.9


def test_different_entities_not_merged(tmp_path):
    """Dissimilar embeddings must NOT be linked (no false identity merge)."""
    t = _tracker(tmp_path)
    v1 = _emb(None, seed=10)
    v2 = _emb(None, seed=99)   # unrelated entity
    assert cosine_similarity(v1, v2) < 0.6

    now = datetime.now()  # relative — cross-camera retention is 24h
    id1, _ = t.record_appearance_sighting(
        "cam_a", "vehicle", v1, now.isoformat(), match_threshold=0.6)
    id2, _ = t.record_appearance_sighting(
        "cam_b", "vehicle", v2, (now + timedelta(seconds=10)).isoformat(),
        match_threshold=0.6)

    assert id1 != id2, "distinct entities must keep separate identities"


def test_gallery_running_mean_keeps_matching(tmp_path):
    """After several matched sightings the gallery embedding still matches new
    views of the same entity (running-mean refinement stays stable)."""
    t = _tracker(tmp_path)
    base = _emb(None, seed=5)
    now = datetime.now()  # relative — cross-camera retention is 24h

    first_id = None
    for i in range(5):
        view = _emb(base, noise=0.05, seed=100 + i)
        eid, _ = t.record_appearance_sighting(
            f"cam_{i}", "person", view,
            (now + timedelta(minutes=i)).isoformat(), match_threshold=0.6)
        if first_id is None:
            first_id = eid
        assert eid == first_id, "all views of one person share one identity"


def test_reappearance_alert_via_appearance(tmp_path):
    """Same entity across 3+ cameras in the window -> frequent_reappearance."""
    t = _tracker(tmp_path)
    base = _emb(None, seed=7)
    now = datetime.now()

    alerts_seen = []
    for i, cam in enumerate(["cam_1", "cam_2", "cam_3"]):
        view = _emb(base, noise=0.04, seed=200 + i)
        _, alerts = t.record_appearance_sighting(
            cam, "vehicle", view,
            (now + timedelta(seconds=i)).isoformat(),
            match_threshold=0.6, id_prefix="veh")
        alerts_seen.extend(alerts)

    assert any(a.alert_type == "frequent_reappearance" for a in alerts_seen)


def test_missing_embedding_mints_new_identity(tmp_path):
    """A None embedding cannot be matched; it must still record safely."""
    t = _tracker(tmp_path)
    now = datetime.now()  # relative — cross-camera retention is 24h
    eid, alerts = t.record_appearance_sighting(
        "cam_a", "vehicle", None, now.isoformat())
    assert eid.startswith("vehicle_")
    assert isinstance(alerts, list)
