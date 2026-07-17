"""
Face sightings are gated on the person detector — pinned.

Found live (2026-07-17): SCRFD recorded a tree and stone paving as faces, in
frames where the person detector correctly found nobody. Those junk sightings
became "Unknown person" tiles on the client-facing Overview. A real face can
only exist inside a detected person, so:
  * no person detections in the frame -> no face is recorded at all,
  * a face candidate must sit inside a (padded) person bbox.
"""

from alibi.vision.frame_intelligence import face_within_person


def test_no_person_boxes_means_no_face():
    assert face_within_person((351, 2, 89, 121), []) is False
    assert face_within_person((351, 2, 89, 121), None) is False


def test_face_inside_person_passes():
    # person standing, face at the top of the person bbox
    person = (400, 50, 60, 180)
    face = (415, 55, 28, 30)
    assert face_within_person(face, [person]) is True


def test_face_far_from_any_person_fails():
    # the live false positive: a "face" in a tree, person detected elsewhere
    person = (10, 400, 40, 100)
    tree_face = (351, 2, 89, 121)
    assert face_within_person(tree_face, [person]) is False


def test_padding_tolerates_slight_overshoot():
    # face centre just above the person bbox top edge (detector overshoot)
    person = (400, 60, 60, 180)
    face = (420, 30, 24, 28)          # centre y=44, above 60 but within 35% pad
    assert face_within_person(face, [person]) is True
