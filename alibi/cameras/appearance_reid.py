"""
Appearance Re-Identification (ReID) embeddings for cross-camera correlation.

WHY THIS EXISTS
---------------
The cross-camera engine used to link entities across cameras only by an EXACT
string key (a plate string, a typed label like "white_toyota_hilux", or an
MD5 hash of a face embedding). Exact-match cannot correlate the SAME vehicle
or person seen at two cameras when there is no readable plate — and hashing a
float embedding is even worse: two near-identical embeddings hash to different
values, so they never match.

This module produces an APPEARANCE EMBEDDING (a fixed-length L2-normalised
vector) from an object crop, so two sightings of the same entity land close
together in vector space and can be matched by cosine similarity.

BACKENDS (auto-selected, best first)
------------------------------------
1. torchreid OSNet (MIT) — a real person/vehicle ReID model. Pretrained
   weights download automatically on first use. Preferred.
   Enable with:  pip install torch torchvision torchreid

If no backend is importable, `AppearanceEmbedder.available` is False and the
caller should skip appearance matching (exact-match still works). We do NOT
fall back to a raw-pixel "embedding": that is not a real ReID signal and would
produce misleading matches.

License note: torchreid is MIT; OSNet weights are research/MIT. No AGPL
`ultralytics` dependency is introduced here.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors, robust to zero norms."""
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).ravel()
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


class AppearanceEmbedder:
    """
    Produces appearance embeddings from BGR image crops using a ReID model.

    Usage:
        emb = AppearanceEmbedder(kind="person")   # or "vehicle"
        if emb.available:
            vec = emb.embed(crop_bgr)              # -> (D,) float32, L2-normalised
    """

    def __init__(self, kind: str = "person", model_name: str = "osnet_x0_25",
                 device: str = "cpu"):
        self.kind = kind
        self.model_name = model_name
        self.device = device
        self.backend: Optional[str] = None
        self._extractor = None
        self._dim: Optional[int] = None
        self._init_backend()

    def _init_backend(self) -> None:
        # torchreid OSNet. The FeatureExtractor lives at different import
        # paths across torchreid versions (torchreid.utils in older releases,
        # torchreid.reid.utils in the current PyPI layout).
        FeatureExtractor = None
        for path in ("torchreid.utils", "torchreid.reid.utils"):
            try:
                module = __import__(path, fromlist=["FeatureExtractor"])
                FeatureExtractor = getattr(module, "FeatureExtractor")
                break
            except Exception:
                continue

        if FeatureExtractor is not None:
            try:
                self._extractor = FeatureExtractor(
                    model_name=self.model_name,
                    model_path="",       # empty -> download pretrained weights
                    device=self.device,
                )
                self.backend = f"torchreid:{self.model_name}"
                return
            except Exception:
                self._extractor = None

        self.backend = None

    @property
    def available(self) -> bool:
        return self._extractor is not None

    @property
    def dim(self) -> Optional[int]:
        return self._dim

    def embed(self, crop_bgr: np.ndarray) -> Optional[np.ndarray]:
        """
        Return an L2-normalised embedding for a single BGR crop, or None if
        no backend is available or the crop is empty.
        """
        if not self.available or crop_bgr is None or crop_bgr.size == 0:
            return None

        # torchreid FeatureExtractor accepts a list of HxWxC BGR arrays.
        feats = self._extractor([crop_bgr])
        vec = np.asarray(feats[0].cpu().numpy() if hasattr(feats[0], "cpu")
                         else feats[0], dtype=np.float32).ravel()
        self._dim = int(vec.shape[0])
        return l2_normalize(vec)

    def embed_batch(self, crops: List[np.ndarray]) -> List[Optional[np.ndarray]]:
        return [self.embed(c) for c in crops]
