"""
Learning from corrections — the two mechanisms that actually work.

SCRFD's weights never change here; fine-tuning a detector from a handful of
clicks would overfit to those clicks. What changes is (1) where each camera
draws its line, learned from confirm/reject answers, and (2) how many
confirmed views of a person we hold, which is what recognition is really
limited by. Both are pinned below.
"""

from datetime import datetime

import numpy as np
import pytest

from alibi.watchlist import face_feedback
from alibi.watchlist.face_match import FaceMatcher
from alibi.watchlist.watchlist_store import WatchlistStore, WatchlistEntry


# ── where the line goes ──────────────────────────────────────────────────

@pytest.fixture
def log(tmp_path):
    return tmp_path / "face_feedback.jsonl"


def _answers(log, pairs, camera="driveway"):
    for score, accepted in pairs:
        face_feedback.record(camera, score, accepted, path=log)


def test_no_evidence_means_no_change(log):
    """A fresh deployment must behave exactly as it does today."""
    assert face_feedback.learned_threshold("driveway", 0.5, path=log) == 0.5


def test_a_few_answers_are_not_a_calibration(log):
    _answers(log, [(0.48, True), (0.52, True), (0.3, False)])
    assert face_feedback.learned_threshold("driveway", 0.5, path=log) == 0.5


def test_it_learns_to_stop_discarding_real_faces(log):
    """Lorraine's case, repeated: faces around 0.4-0.48 keep being confirmed,
    junk sits near 0.36. The line should come down to catch the real ones."""
    _answers(log, [(0.481, True), (0.44, True), (0.46, True), (0.52, True), (0.61, True),
                   (0.36, False), (0.33, False), (0.35, False)])
    learned = face_feedback.learned_threshold("driveway", 0.5, path=log)
    assert learned < 0.5
    assert 0.36 < learned <= 0.44        # above the junk, at or below the real faces


def test_it_learns_to_tighten_when_a_camera_produces_junk(log):
    """The opposite camera: everything under 0.55 has been rejected."""
    _answers(log, [(0.38, False), (0.42, False), (0.47, False), (0.51, False), (0.44, False),
                   (0.58, True), (0.62, True), (0.71, True)], camera="gate")
    learned = face_feedback.learned_threshold("gate", 0.5, path=log)
    assert learned > 0.5


def test_learning_stays_inside_sane_bounds(log):
    """However lopsided the answers, never enrol texture and never go back to
    discarding real faces."""
    _answers(log, [(0.9, False)] * 5 + [(0.85, True)] * 5)
    t = face_feedback.learned_threshold("driveway", 0.5, path=log)
    assert face_feedback.FLOOR <= t <= face_feedback.CEILING

    _answers(log, [(0.1, True)] * 6, camera="dark")
    _answers(log, [(0.05, False)] * 6, camera="dark")
    t2 = face_feedback.learned_threshold("dark", 0.5, path=log)
    assert face_feedback.FLOOR <= t2 <= face_feedback.CEILING


def test_cameras_learn_separately(log):
    _answers(log, [(0.481, True), (0.44, True), (0.46, True), (0.52, True), (0.61, True),
                   (0.36, False), (0.33, False), (0.35, False)], camera="driveway")
    assert face_feedback.learned_threshold("driveway", 0.5, path=log) < 0.5
    assert face_feedback.learned_threshold("gate", 0.5, path=log) == 0.5


def test_a_ruined_log_does_not_take_the_cameras_down(log):
    log.write_text("not json\n{\"ts\":\"x\"}\n\n")
    assert face_feedback.learned_threshold("driveway", 0.5, path=log) == 0.5


def test_the_summary_says_what_is_still_needed(log):
    _answers(log, [(0.48, True), (0.36, False)])
    s = face_feedback.summary("driveway", path=log)
    assert s["decisions"] == 2 and s["confirmed"] == 1 and s["rejected"] == 1
    assert s["needed_before_learning"] == face_feedback.MIN_DECISIONS - 2


# ── how many views of a person we hold ───────────────────────────────────

def _entry(pid, label, emb, ref="sighting:x"):
    # Real callers hand in plain-float lists (embedding.tolist()); mirror that.
    emb = np.asarray(emb, dtype=np.float32).tolist() if len(emb) else []
    return WatchlistEntry(person_id=pid, label=label, embedding=emb,
                          added_ts=datetime.utcnow().isoformat(), source_ref=ref,
                          metadata={})


def _store(tmp_path):
    return WatchlistStore(storage_path=str(tmp_path / "watchlist.jsonl"))


def test_confirming_a_person_again_adds_a_view_instead_of_replacing_one(tmp_path):
    """The bug this fixes: enrolling Lorraine head-on then again looking down
    used to leave ONE template — the second overwrote the first, so the angle
    you corrected for was the only one that worked."""
    s = _store(tmp_path)
    head_on = np.ones(512, dtype=np.float32)
    looking_down = np.concatenate([np.ones(256), np.zeros(256)]).astype(np.float32)
    s.add_entry(_entry("lorraine-1", "Lorraine", head_on))
    s.add_entry(_entry("lorraine-1", "Lorraine", looking_down))

    gallery = s.get_galleries()["lorraine-1"]
    assert gallery.shape == (2, 512)


def test_matching_uses_the_best_view_not_the_latest(tmp_path):
    """Someone enrolled at two angles must be found at EITHER."""
    s = _store(tmp_path)
    head_on = np.ones(512, dtype=np.float32)
    looking_down = np.concatenate([np.ones(256), np.zeros(256)]).astype(np.float32)
    s.add_entry(_entry("lorraine-1", "Lorraine", head_on))
    s.add_entry(_entry("lorraine-1", "Lorraine", looking_down))

    m = FaceMatcher()
    galleries = s.get_galleries()
    assert m.cosine_similarity(head_on, galleries["lorraine-1"]) == pytest.approx(1.0, abs=1e-5)
    assert m.cosine_similarity(looking_down, galleries["lorraine-1"]) == pytest.approx(1.0, abs=1e-5)


def test_renaming_does_not_pile_up_duplicate_views(tmp_path):
    """Renaming re-appends the same vector; it must not inflate the gallery."""
    s = _store(tmp_path)
    emb = np.ones(512, dtype=np.float32)
    s.add_entry(_entry("mike-1", "Mike", emb))
    s.add_entry(_entry("mike-1", "Michael", emb))          # a rename
    assert s.get_galleries()["mike-1"].shape == (1, 512)
    assert s._get_active_entries()["mike-1"].label == "Michael"


def test_removing_a_person_removes_their_whole_gallery(tmp_path):
    s = _store(tmp_path)
    s.add_entry(_entry("gone-1", "Gone", np.ones(512, dtype=np.float32)))
    s.add_entry(_entry("gone-1", "Gone", np.zeros(512, dtype=np.float32) + 2))
    s.add_entry(_entry("gone-1", "Gone", [], ref="REMOVED"))
    assert "gone-1" not in s.get_galleries()


def test_a_single_embedding_still_matches_the_old_way(tmp_path):
    """Backwards compatible: a 1-D vector is still a valid comparison target."""
    m = FaceMatcher()
    v = np.ones(512, dtype=np.float32)
    assert m.cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-5)
    assert m.cosine_similarity(v, np.zeros(512, dtype=np.float32)) == 0.0


def test_mismatched_dimensions_score_zero_rather_than_explode():
    m = FaceMatcher()
    assert m.cosine_similarity(np.ones(512), np.ones((3, 128))) == 0.0
