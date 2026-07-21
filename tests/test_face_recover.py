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
    """Stands in for SCRFD: reports a face at a fixed spot in whatever it's given."""

    def __init__(self, at=(20, 10, 40, 40)):
        self.at = at
        self.seen = None

    def detect_and_extract(self, img):
        self.seen = img
        x, y, w, h = self.at
        return img[y:y + h, x:x + w], self.at


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

    # The detector ran on an enlarged copy, so map back by that factor...
    factor = r["upscale"]
    pad = int(160 * face_recover.CROP_PAD)
    expected = (300 - pad + int(20 / factor), 200 - pad + int(10 / factor))
    assert r["bbox"][:2] == expected
    # ...and the result must sit inside the person's box region, not at 0,0.
    assert r["bbox"][0] > 250 and r["bbox"][1] > 150


def test_no_face_is_reported_honestly():
    class _Blind:
        def detect_and_extract(self, img):
            return None

    assert face_recover.find_face(_frame(), [10, 10, 50, 100], _Blind(), _Embedder()) is None


def test_embedding_is_returned_as_plain_floats():
    r = face_recover.find_face(_frame(), [100, 100, 60, 120], _Detector(), _Embedder())
    assert len(r["embedding"]) == 512
    assert all(isinstance(v, float) for v in r["embedding"][:5])
