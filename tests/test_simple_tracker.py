"""
Dependency-free tracker — the piece that replaces ultralytics (AGPL).

Detection says "a person is here"; tracking says "the same person as last frame".
Rules and incidents need the second: "loitering" is meaningless unless you know
it's one person standing still rather than thirty strangers.
"""

from datetime import datetime, timedelta

from alibi.vision.simple_tracker import (
    Detection, SimpleTracker, detections_from_gatekeeper, iou,
)

T0 = datetime(2026, 7, 17, 8, 0, 0)


def _d(x, y, w=40, h=80, cls="person", conf=0.9):
    return Detection(bbox=(x, y, w, h), confidence=conf, class_name=cls)


# --- IoU -------------------------------------------------------------------- #

def test_iou_basics():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0
    assert 0.1 < iou((0, 0, 10, 10), (5, 0, 10, 10)) < 0.5
    assert iou((0, 0, 0, 0), (0, 0, 10, 10)) == 0.0        # degenerate box


# --- identity across frames ------------------------------------------------- #

def test_the_same_person_keeps_one_id_while_walking():
    t = SimpleTracker()
    t.update([_d(100, 100)], T0)
    first = list(t.tracks)[0]
    for i, x in enumerate([106, 112, 118], start=1):        # small steps, boxes overlap
        t.update([_d(x, 100)], T0 + timedelta(seconds=i))
    assert list(t.tracks) == [first]                        # still one person
    assert t.tracks[first].hits == 4


def test_two_people_get_two_ids_and_do_not_swap():
    t = SimpleTracker()
    t.update([_d(100, 100), _d(400, 100)], T0)
    assert len(t.tracks) == 2
    left = min(t.tracks, key=lambda k: t.tracks[k].bbox[0])
    right = max(t.tracks, key=lambda k: t.tracks[k].bbox[0])
    t.update([_d(106, 100), _d(406, 100)], T0 + timedelta(seconds=1))
    assert len(t.tracks) == 2
    assert t.tracks[left].bbox[0] == 106                    # each kept its own identity
    assert t.tracks[right].bbox[0] == 406


def test_a_new_arrival_gets_a_new_id():
    t = SimpleTracker()
    t.update([_d(100, 100)], T0)
    t.update([_d(100, 100), _d(500, 100)], T0 + timedelta(seconds=1))
    assert len(t.tracks) == 2


def test_a_person_never_becomes_a_car():
    # Same box, different class -> must not be associated.
    t = SimpleTracker()
    t.update([_d(100, 100, cls="person")], T0)
    t.update([_d(100, 100, cls="car")], T0 + timedelta(seconds=1))
    assert len(t.tracks) == 2
    assert {tr.class_name for tr in t.tracks.values()} == {"person", "car"}


def test_a_jump_too_far_is_treated_as_someone_new():
    t = SimpleTracker()
    t.update([_d(100, 100)], T0)
    t.update([_d(900, 100)], T0 + timedelta(seconds=1))      # no overlap
    assert len(t.tracks) == 2


# --- retiring --------------------------------------------------------------- #

def test_a_track_retires_after_it_stops_being_seen():
    t = SimpleTracker(max_age=2)
    t.update([_d(100, 100)], T0)
    for i in range(1, 4):
        t.update([], T0 + timedelta(seconds=i))              # gone
    assert t.tracks == {}


def test_a_brief_miss_does_not_lose_the_person():
    t = SimpleTracker(max_age=2)
    t.update([_d(100, 100)], T0)
    tid = list(t.tracks)[0]
    t.update([], T0 + timedelta(seconds=1))                  # missed one frame
    t.update([_d(104, 100)], T0 + timedelta(seconds=2))      # back
    assert list(t.tracks) == [tid]                           # same person


def test_active_only_returns_tracks_seen_this_frame():
    t = SimpleTracker(max_age=3)
    t.update([_d(100, 100)], T0)
    t.update([], T0 + timedelta(seconds=1))
    assert t.active() == {}                                  # not seen now
    assert len(t.tracks) == 1                                # but not retired yet


def test_min_hits_filters_one_frame_flickers():
    t = SimpleTracker()
    t.update([_d(100, 100)], T0)
    assert t.active(min_hits=3) == {}                        # not believed yet
    t.update([_d(103, 100)], T0 + timedelta(seconds=1))
    t.update([_d(106, 100)], T0 + timedelta(seconds=2))
    assert len(t.active(min_hits=3)) == 1                    # now it's real


# --- the seam that removes the ultralytics coupling ------------------------- #

class _FakeDet:
    def __init__(self, bbox, conf, name):
        self.bbox = bbox
        self.confidence = conf
        self.class_name = name
        self.class_id = 0


def test_gatekeeper_output_converts_without_yolo():
    """The whole point: tracking stops caring which detector produced the boxes."""
    result = {"detections": [_FakeDet((10, 20, 30, 40), 0.9, "person"),
                             _FakeDet((50, 60, 20, 20), 0.7, "car")]}
    dets = detections_from_gatekeeper(result)
    assert [d.class_name for d in dets] == ["person", "car"]
    assert dets[0].bbox == (10, 20, 30, 40) and dets[0].confidence == 0.9

    t = SimpleTracker()
    tracks = t.update(dets, T0)
    assert len(tracks) == 2


def test_malformed_detections_are_skipped_not_fatal():
    class Bad:
        bbox = "nonsense"
        confidence = 0.5
        class_name = "person"
    assert detections_from_gatekeeper({"detections": [Bad()]}) == []
    assert detections_from_gatekeeper({}) == []
    assert detections_from_gatekeeper(None) == []


def test_tracker_is_deterministic():
    dets = [_d(100, 100), _d(300, 100)]
    a, b = SimpleTracker(), SimpleTracker()
    ra = a.update(dets, T0); rb = b.update(dets, T0)
    assert sorted(ra) == sorted(rb)
