"""
What the system knows about who is who must survive a restart. Pinned.

Found 2026-07-22: the appearance galleries lived only in RAM and
_new_entity_counter reset to 0 on boot. So every restart threw away every
appearance ever learned AND started minting ids from vehicle_000001 again —
straight into the trail of whatever vehicle_000001 used to be. Restarts did
not merely forget identities, they merged different vehicles into one. The
live archive showed 9 ids across 3 days with vehicle_000001 holding 4,368
sightings, having been restarted repeatedly.

Nothing here is about disk retention: the sightings file is append-only and
never deleted. This is about the memory that gives those rows meaning.
"""

import numpy as np
import pytest

from alibi.cameras.cross_camera import CrossCameraTracker


def _tracker(tmp_path, **kw):
    kw.setdefault("retention_hours", 24 * 180)
    return CrossCameraTracker(
        storage_path=str(tmp_path / "sightings.jsonl"),
        gallery_path=str(tmp_path / "galleries.jsonl"),
        **kw,
    )


def _emb(seed, dim=512):
    rng = np.random.default_rng(seed)
    return rng.normal(size=dim).astype(np.float32)


def test_a_learned_identity_survives_a_restart(tmp_path):
    """Deliberately checks the SECOND car.

    Checking the first proves nothing: with the bug, the counter also resets,
    so the re-minted id collides with the original and the assertion passes for
    exactly the reason we are trying to catch. The second car's id can only be
    recovered by genuinely remembering.
    """
    car_a, car_b = _emb(1), _emb(2)
    t1 = _tracker(tmp_path)
    a, _ = t1.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car_a,
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")
    b, _ = t1.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car_b,
        timestamp="2026-07-22T09:00:00", id_prefix="vehicle")
    assert a != b

    # Restart: brand new object, same files.
    t2 = _tracker(tmp_path)
    again, _ = t2.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car_b * 1.01,
        timestamp="2026-07-22T18:00:00", id_prefix="vehicle")

    assert again == b, "the same car became a different vehicle after a restart"


def test_ids_are_never_reused_after_a_restart(tmp_path):
    """The corruption, precisely: a DIFFERENT car must not inherit the first
    car's id just because the counter forgot how far it had got."""
    t1 = _tracker(tmp_path)
    first, _ = t1.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(1),
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")

    t2 = _tracker(tmp_path)
    other, _ = t2.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(999),
        timestamp="2026-07-22T18:00:00", id_prefix="vehicle")

    assert other != first
    assert t2._new_entity_counter > t1._new_entity_counter - 1


def test_the_counter_recovers_even_with_no_gallery_snapshot(tmp_path):
    """Belt and braces: if the snapshot is lost or corrupt, the archive itself
    still tells us the highest id ever minted."""
    t1 = _tracker(tmp_path)
    for i in range(3):
        t1.record_appearance_sighting(
            camera_id="gate", entity_type="vehicle", embedding=_emb(i),
            timestamp=f"2026-07-22T0{i + 1}:00:00", id_prefix="vehicle")

    (tmp_path / "galleries.jsonl").write_text("total garbage\n")

    t2 = _tracker(tmp_path)
    fresh, _ = t2.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(500),
        timestamp="2026-07-22T20:00:00", id_prefix="vehicle")
    assert fresh == "vehicle_000004", f"reused or skipped an id: {fresh}"


def test_a_car_that_returns_after_a_long_absence_is_still_itself(tmp_path):
    """The recency gate used to skip any entity with no sighting in the
    in-memory window, which quietly undid the point of remembering."""
    car = _emb(7)
    t = _tracker(tmp_path)
    eid, _ = t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car,
        timestamp="2026-01-05T09:00:00", id_prefix="vehicle")

    # Months later. Nothing in the in-memory window for this entity.
    t._sightings.clear()
    again, _ = t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car * 0.98,
        timestamp="2026-09-05T09:00:00", id_prefix="vehicle")
    assert again == eid


def test_different_cars_still_stay_apart(tmp_path):
    """Remembering more must not mean matching more loosely."""
    t = _tracker(tmp_path)
    a, _ = t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(1),
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")
    b, _ = t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(2),
        timestamp="2026-07-22T09:00:00", id_prefix="vehicle")
    assert a != b


def test_the_sightings_archive_is_never_truncated(tmp_path):
    """The in-memory window is a working set, not a retention policy."""
    t = _tracker(tmp_path, retention_hours=1)
    t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(1),
        timestamp="2020-01-01T00:00:00", id_prefix="vehicle")
    t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(2),
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")

    lines = [l for l in (tmp_path / "sightings.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 2, "an old sighting was deleted from the archive"


def test_galleries_survive_a_corrupt_trailing_write(tmp_path):
    """Snapshots are append-only, last valid wins — a half-written final line
    must not cost us everything learned before it."""
    car = _emb(3)
    t1 = _tracker(tmp_path)
    eid, _ = t1.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car,
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")
    with open(tmp_path / "galleries.jsonl", "a") as f:
        f.write("{ truncated\n")

    t2 = _tracker(tmp_path)
    again, _ = t2.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=car,
        timestamp="2026-07-22T09:00:00", id_prefix="vehicle")
    assert again == eid


def test_galleries_live_beside_their_sightings(tmp_path):
    """A tracker pointed at a temporary archive must not read or write the
    real one. Getting this wrong made every test share one gallery file and
    inherit whatever the previous test had learned."""
    t = CrossCameraTracker(storage_path=str(tmp_path / "xcam.jsonl"),
                           retention_hours=24)
    assert t.gallery_path.parent == tmp_path
    t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(1),
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")
    assert t.gallery_path.exists()


def test_embeddings_from_a_different_model_are_ignored_not_scored(tmp_path):
    """If the ReID backend changes, old vectors are meaningless — comparing
    against them would either crash or score noise."""
    t = _tracker(tmp_path)
    # A leftover from an older backend, well clear of the next id to be minted
    # so a collision can't make this pass for the wrong reason.
    t._galleries["vehicle"]["vehicle_000099"] = _emb(1, dim=128)
    fresh, _ = t.record_appearance_sighting(
        camera_id="gate", entity_type="vehicle", embedding=_emb(1, dim=512),
        timestamp="2026-07-22T08:00:00", id_prefix="vehicle")
    assert fresh != "vehicle_000099", "scored against an incompatible embedding"
