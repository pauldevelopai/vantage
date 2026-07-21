"""
Recover a face from a person detection, on demand.

Most rows on the People page are person DETECTIONS, not face sightings: at
pavement distance the detector finds the body but the face pass never ran on
that crop. Those rows carry no embedding, so there is nothing to name and
nothing to look up — they were dead ends.

This runs the face pass over just that person's box, when the operator asks
for it. If a readable face is in there we get a real embedding and the row
becomes a first-class face sighting: nameable, and matched against everyone
already enrolled. If there isn't one, we say so plainly — a person 20px wide
has no face to recover, and no amount of upscaling invents one.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

# The person box is a body; the face is a small part of it. Pad so a face at
# the very top edge isn't clipped, then upscale — SCRFD has a minimum size it
# can resolve, and distant crops land under it.
CROP_PAD = 0.25
UPSCALE_TARGET = 320       # shortest side we aim for before detecting
MAX_UPSCALE = 6.0          # beyond this we are magnifying noise, not detail


def crop_person(frame: np.ndarray, bbox, pad: float = CROP_PAD) -> Optional[np.ndarray]:
    """Cut the person's box out of the frame, with padding, in frame pixels."""
    if frame is None or frame.size == 0 or not bbox or len(bbox) != 4:
        return None
    x, y, w, h = (int(v) for v in bbox)
    if w <= 0 or h <= 0:
        return None
    p = int(max(w, h) * pad)
    fh, fw = frame.shape[:2]
    x0, y0 = max(0, x - p), max(0, y - p)
    x1, y1 = min(fw, x + w + p), min(fh, y + h + p)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = frame[y0:y1, x0:x1]
    return crop if crop.size else None


def upscale(crop: np.ndarray, target: int = UPSCALE_TARGET,
            max_factor: float = MAX_UPSCALE) -> Tuple[np.ndarray, float]:
    """Enlarge a small crop toward `target` on its shortest side.

    Returns (image, factor) so a bbox found in the enlarged image can be mapped
    back to real frame coordinates.
    """
    import cv2

    if crop is None or crop.size == 0:
        return crop, 1.0
    short = min(crop.shape[0], crop.shape[1])
    if short <= 0 or short >= target:
        return crop, 1.0
    factor = min(target / short, max_factor)
    out = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    return out, factor


_DETECTOR = None
_EMBEDDER = None


def _models():
    """Load SCRFD and ArcFace once. Both take seconds to construct, and this
    runs behind a button a person is waiting on."""
    global _DETECTOR, _EMBEDDER
    if _DETECTOR is None:
        from alibi.watchlist.face_detect import FaceDetector
        _DETECTOR = FaceDetector()
    if _EMBEDDER is None:
        from alibi.watchlist.face_embed import FaceEmbedder
        _EMBEDDER = FaceEmbedder()
    return _DETECTOR, _EMBEDDER


def find_face(frame: np.ndarray, bbox, detector=None, embedder=None) -> Optional[dict]:
    """Look for one readable face inside a person box.

    Returns {"bbox": (x, y, w, h) in FRAME coords, "embedding": [...],
             "confidence": float, "upscale": float} or None when there is no
    face to recover — which is the common, honest outcome for distant people.
    """
    crop = crop_person(frame, bbox)
    if crop is None:
        return None

    big, factor = upscale(crop)

    if detector is None:
        detector, _cached_embedder = _models()
        embedder = embedder or _cached_embedder

    found = detector.detect_and_extract(big)
    if not found:
        return None
    face_img, (fx, fy, fw, fh) = found
    if face_img is None or getattr(face_img, "size", 0) == 0:
        return None

    if embedder is None:
        _d, embedder = _models()
    emb = embedder.generate_embedding(face_img)
    if emb is None or len(emb) == 0:
        return None

    # Map back: enlarged-crop coords → crop coords → frame coords.
    x, y, w, h = (int(v) for v in bbox)
    p = int(max(w, h) * CROP_PAD)
    ox, oy = max(0, x - p), max(0, y - p)
    return {
        "bbox": (int(ox + fx / factor), int(oy + fy / factor),
                 int(fw / factor), int(fh / factor)),
        "embedding": [float(v) for v in np.asarray(emb).ravel()],
        "confidence": 1.0 if factor == 1.0 else round(1.0 / factor, 3),
        "upscale": round(factor, 2),
    }
