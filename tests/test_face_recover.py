"""Recovering a face from a person detection — the geometry, mainly.

The bbox we hand back has to be in FRAME coordinates, not crop coordinates and
not the coordinates of the enlarged copy we ran the detector on. Get that wrong
and the enrolled face is a picture of somebody's knee.
"""

import numpy as np

from alibi.watchlist import face_recover


def _frame(w=640, h=524):
    return np.full((h, w, 3), 128, dtype=np.uint8)


class _Detector:
    """Stands in for SCRFD: reports a face at a fixed spot, same score at every
    scale, so the scale sweep picks the first (1.0x) and the maths stays checkable."""

    def __init__(self, at=(20, 10, 40, 40), score=0.48):
        self.at = at
        self.score = score
        self.scales_seen = []

    def detect_scored(self, img):
        self.scales_seen.append(img.shape[:2])
        return [(self.at, self.score)]


class _Embedder:
    def generate_embedding(self, face):
        return np.ones(512, dtype=np.float32)


def test_crop_person_pads_and_clips_to_frame():
    crop = face_recover.crop_person(_frame(), [0, 0, 40, 80])
    # Padding is 25% of the long side (20px), clipped at the frame edge.
    assert crop.shape[1] == 40 + 20      # left edge clipped, right padded
    assert crop.shape[0] == 80 + 20


def test_crop_person_rejects_nonsense():
    assert face_recover.crop_person(_frame(), [0, 0, 0, 0]) is None
    assert face_recover.crop_person(_frame(), [1, 2, 3]) is None
    assert face_recover.crop_person(None, [0, 0, 10, 10]) is None


def test_upscale_enlarges_small_crops_but_leaves_big_ones():
    small = np.zeros((80, 60, 3), dtype=np.uint8)     # 60 short side → 5.3x, under the cap
    out, factor = face_recover.upscale(small, target=320)
    assert factor > 1
    assert min(out.shape[:2]) >= 320 - 1

    big = np.zeros((400, 400, 3), dtype=np.uint8)
    out, factor = face_recover.upscale(big, target=320)
    assert factor == 1.0
    assert out.shape == big.shape


def test_upscale_is_capped():
    tiny = np.zeros((4, 4, 3), dtype=np.uint8)
    _, factor = face_recover.upscale(tiny, target=320, max_factor=6.0)
    assert factor == 6.0        # not 80x — that magnifies noise, not detail


def test_found_bbox_is_in_frame_coordinates():
    # Person low-right in the frame, so crop-relative and frame-relative
    # coordinates cannot be confused with each other.
    det = _Detector(at=(20, 10, 40, 40))
    r = face_recover.find_face(_frame(), [300, 200, 80, 160], det, _Embedder())
    assert r is not None

    # The detector may have run on a resized copy, so map back by that factor...
    factor = r["scale"]
    pad = int(160 * face_recover.CROP_PAD)
    expected = (300 - pad + int(20 / factor), 200 - pad + int(10 / factor))
    assert r["bbox"][:2] == expected
    # ...and the result must sit inside the person's box region, not at 0,0.
    assert r["bbox"][0] > 250 and r["bbox"][1] > 150


def test_tries_several_scales_and_keeps_the_best_scoring():
    """Bigger is not reliably better — Lorraine's face scored 0.481 at 1x and
    0.354 at 6x. Whichever scale scores highest is the one we use."""

    class _ScaleFussy:
        def detect_scored(self, img):
            # Scores best on the untouched crop, worse the more it's enlarged.
            short = min(img.shape[:2])          # 200 on the untouched crop
            return [((5, 5, 20, 20), 0.9 if short <= 200 else 0.2)]

    det = _ScaleFussy()
    r = face_recover.find_face(_frame(), [100, 100, 120, 160], det, _Embedder())
    assert r["score"] == 0.9
    assert r["scale"] == 1.0        # not the largest scale — the best one


def test_a_faint_face_is_still_returned_with_its_score():
    """The live pipeline's 0.5 cutoff threw away a real face at 0.481. Here the
    human is the gate, so we hand back the weak one AND how weak it is."""
    r = face_recover.find_face(_frame(), [100, 100, 60, 120],
                               _Detector(score=0.481), _Embedder())
    assert r["score"] == 0.481
    assert face_recover.RECOVER_THRESHOLD < 0.5


def test_a_preview_of_the_face_comes_back_for_a_human_to_check():
    r = face_recover.find_face(_frame(), [100, 100, 60, 120], _Detector(), _Embedder())
    assert r["face_jpeg"][:2] == b"\xff\xd8"      # a real JPEG, not a promise


def test_no_face_is_reported_honestly():
    class _Blind:
        def detect_scored(self, img):
            return []

    assert face_recover.find_face(_frame(), [10, 10, 50, 100], _Blind(), _Embedder()) is None


def test_embedding_is_returned_as_plain_floats():
    r = face_recover.find_face(_frame(), [100, 100, 60, 120], _Detector(), _Embedder())
    assert len(r["embedding"]) == 512
    assert all(isinstance(v, float) for v in r["embedding"][:5])


def test_preview_is_enlarged_but_the_embedding_is_not():
    """A recovered face can be 20x24. Blow the preview up so a person can judge
    it — but the embedding must come from the original pixels, or every match
    afterwards is computed against an interpolation."""
    seen = {}

    class _RecordingEmbedder:
        def generate_embedding(self, face):
            seen['shape'] = face.shape[:2]
            return np.ones(512, dtype=np.float32)

    det = _Detector(at=(5, 5, 20, 24))
    r = face_recover.find_face(_frame(), [100, 100, 60, 120], det, _RecordingEmbedder())
    assert seen['shape'] == (24, 20)             # embedded at native size
    assert len(r["face_jpeg"]) > 0
    import cv2
    shown = cv2.imdecode(np.frombuffer(r["face_jpeg"], np.uint8), cv2.IMREAD_COLOR)
    assert min(shown.shape[:2]) >= face_recover.PREVIEW_MIN - 1   # shown enlarged
