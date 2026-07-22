"""
Keep the pictures that carry an answer; sweep the empty driveway at 3am.

Nothing swept the frame store, so it grew forever — 23,195 files and 1.7GB in
five days on the live box, of which 89% were referenced by nothing at all.
This decides what goes. Deletion is irreversible and these frames are the only
copy of the evidence behind everything the system has said, so the safety
properties matter more than the space saved.
"""

import json
from datetime import datetime, timedelta

import pytest

from alibi.cameras import frame_retention as fr


NOW = datetime(2026, 7, 22, 12, 0, 0)


def _frames(*specs):
    """(id, mtime, size) — specs are (id, days_old)."""
    return [(fid, NOW - timedelta(days=age), 100_000) for fid, age in specs]


def _value(forever=(), referenced=()):
    v = fr.Value()
    for fid in forever:
        v.note(fid, "test", forever=True)
    for fid in referenced:
        v.note(fid, "test", forever=False)
    return v


# ── the rule that matters ────────────────────────────────────────────────

def test_evidence_is_never_deleted_however_old():
    """A frame someone was named from is the only copy of that answer."""
    plan = fr.plan_sweep(_frames(("keep", 3650)), _value(forever=["keep"]), now=NOW)
    assert plan.delete == []
    assert plan.keep_forever == 1


def test_an_orphan_that_nothing_found_anything_in_is_swept():
    plan = fr.plan_sweep(_frames(("junk", 30)), _value(), now=NOW)
    assert plan.delete == ["junk"]
    assert plan.bytes_freed == 100_000


def test_a_recent_orphan_is_left_alone_so_you_can_still_look():
    plan = fr.plan_sweep(_frames(("today", 1)), _value(), now=NOW)
    assert plan.delete == []
    assert plan.keep_recent == 1


def test_an_ordinary_detection_is_kept_for_a_season_then_swept():
    young, old = _frames(("young", 30), ("old", 120))
    plan = fr.plan_sweep([young, old], _value(referenced=["young", "old"]), now=NOW)
    assert plan.delete == ["old"]
    assert plan.keep_referenced == 1


def test_forever_beats_a_weaker_claim_on_the_same_frame():
    """A frame can be both an ordinary detection and the shot you named someone
    from. The strongest claim has to win, whichever is recorded first."""
    v = fr.Value()
    v.note("f", "a real detection", forever=False)
    v.note("f", "how you recognise Lorraine", forever=True)
    assert "f" in v.forever and "f" not in v.referenced

    v2 = fr.Value()
    v2.note("f", "how you recognise Lorraine", forever=True)
    v2.note("f", "a real detection", forever=False)
    assert "f" in v2.forever and "f" not in v2.referenced

    plan = fr.plan_sweep(_frames(("f", 3650)), v, now=NOW)
    assert plan.delete == []


def test_the_plan_says_why_things_were_kept():
    v = fr.Value()
    v.note("a", "a readable number plate", forever=True)
    v.note("b", "a readable number plate", forever=True)
    v.note("c", "you wrote a note on it", forever=True)
    plan = fr.plan_sweep(_frames(("a", 500), ("b", 500), ("c", 500)), v, now=NOW)
    assert plan.reasons == {"a readable number plate": 2, "you wrote a note on it": 1}


# ── failing safe ─────────────────────────────────────────────────────────

def test_a_dry_run_deletes_nothing(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "old.jpg").write_bytes(b"x" * 100)
    import os
    old = (NOW - timedelta(days=400)).timestamp()
    os.utime(frames / "old.jpg", (old, old))

    data = tmp_path / "data"
    data.mkdir()
    plan = fr.sweep(dry_run=True, frames_dir=frames, data_dir=data)
    assert (frames / "old.jpg").exists(), "a dry run deleted a file"
    assert plan.deleting == 1


def test_unreadable_evidence_aborts_the_sweep_rather_than_deleting_everything(tmp_path, monkeypatch):
    """The dangerous failure: if we cannot read the stores, every frame looks
    like an orphan and a sweep would take the lot."""
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "precious.jpg").write_bytes(b"x" * 100)
    import os
    old = (NOW - timedelta(days=400)).timestamp()
    os.utime(frames / "precious.jpg", (old, old))

    def _boom(*a, **k):
        raise OSError("disk is having a day")

    monkeypatch.setattr(fr, "collect_value", _boom)
    plan = fr.sweep(dry_run=False, frames_dir=frames, data_dir=tmp_path / "data")

    assert plan.aborted
    assert plan.delete == []
    assert (frames / "precious.jpg").exists(), "swept blind and destroyed evidence"


def test_a_real_sweep_removes_only_what_it_planned(tmp_path):
    import os
    frames = tmp_path / "frames"
    frames.mkdir()
    for name, age in (("old", 400), ("new", 1)):
        p = frames / f"{name}.jpg"
        p.write_bytes(b"x" * 100)
        t = (datetime.now() - timedelta(days=age)).timestamp()
        os.utime(p, (t, t))

    data = tmp_path / "data"
    data.mkdir()
    plan = fr.sweep(dry_run=False, frames_dir=frames, data_dir=data)
    assert plan.delete == ["old"]
    assert not (frames / "old.jpg").exists()
    assert (frames / "new.jpg").exists()


# ── reading the evidence stores ──────────────────────────────────────────

def test_frame_ids_are_found_in_urls_and_json():
    assert fr.frame_ids_in("/api/cameras/frames/abc123def456.jpg") == {"abc123def456"}
    assert fr.frame_ids_in(json.dumps({"frame_url": "/api/cameras/frames/deadbeef00.jpg"})) \
        == {"deadbeef00"}
    assert fr.frame_ids_in(None) == set()
    assert fr.frame_ids_in("no frames here") == set()


def test_a_note_you_wrote_protects_a_frame_for_good(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "frame_notes.json").write_text(json.dumps({
        "noted": {"note": "Lorraine, delivering"},
        "described": {"description": "A white sedan in the driveway"},
        "empty": {},
    }))
    value = fr.collect_value(data)
    assert "noted" in value.forever
    assert "described" in value.forever
    assert "empty" not in value.all_kept
