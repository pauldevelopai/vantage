"""
Tests for the ArcFace (InsightFace) face-embedding backend.

Requires insightface + onnxruntime and downloads a model pack on first run, so
the module skips cleanly when insightface isn't installed.
"""

import numpy as np
import pytest

pytest.importorskip("insightface")

from alibi.watchlist.face_embed import FaceEmbedder
from alibi.watchlist.face_match import FaceMatcher


@pytest.fixture(scope="module")
def embedder():
    return FaceEmbedder()


def test_selects_arcface(embedder):
    assert embedder.method == "arcface"
    assert embedder.embedding_size == 512


def test_embedding_is_normalised_512d(embedder):
    rng = np.random.default_rng(0)
    crop = rng.integers(0, 255, (150, 110, 3), dtype=np.uint8)
    vec = embedder.generate_embedding(crop)
    assert vec.shape == (512,)
    assert vec.dtype == np.float32
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-3  # L2-normalised


def test_empty_crop_is_safe(embedder):
    vec = embedder.generate_embedding(np.zeros((0, 0, 3), dtype=np.uint8))
    assert vec.shape == (512,)
    assert not np.any(np.isnan(vec))


def test_same_crop_deterministic(embedder):
    rng = np.random.default_rng(1)
    crop = rng.integers(0, 255, (140, 100, 3), dtype=np.uint8)
    a = embedder.generate_embedding(crop)
    b = embedder.generate_embedding(crop.copy())
    # Identical input -> identical embedding -> cosine 1.0
    assert float(a @ b) > 0.999


def test_matcher_accepts_arcface_vectors(embedder):
    rng = np.random.default_rng(2)
    base = rng.integers(40, 210, (150, 110, 3), dtype=np.uint8)
    a = embedder.generate_embedding(np.clip(base + rng.integers(-6, 6, base.shape), 0, 255).astype(np.uint8))
    b = embedder.generate_embedding(np.clip(base + rng.integers(-6, 6, base.shape), 0, 255).astype(np.uint8))
    m = FaceMatcher()
    sim = m.cosine_similarity(a, b)
    assert -1.0 <= sim <= 1.0
