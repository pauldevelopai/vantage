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
# the very top edge isn't clipped.
CROP_PAD = 0.25
UPSCALE_TARGET = 320       # shortest side we aim for before detecting
MAX_UPSCALE = 6.0          # beyond this we are magnifying noise, not detail

# Detection threshold for THIS path only. The live pipeline keeps SCRFD's
# default 0.5, which is right when nobody is watching. Here a person has
# deliberately asked about one shot and is shown the face we found before
# anything is saved, so we can afford to look harder: a driveway face, tilted
# down at a phone and lit from above, scored 0.481 — a real face, thrown away
# by a hundredth. The human confirming is the gate, not the threshold.
RECOVER_THRESHOLD = 0.35

# Try the crop at several sizes and keep the best-scoring face. Upscaling is
# NOT reliably better: cubic interpolation invents no detail, and on that same
# driveway face it made things worse at every step (0.481 at 1x → 0.354 at 6x).
SCALES = (1.0, 1.5, 2.0, 3.0)


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
        _DETECTOR = FaceDetector(confidence_threshold=RECOVER_THRESHOLD)
    if _EMBEDDER is None:
        from alibi.watchlist.face_embed import FaceEmbedder
        _EMBEDDER = FaceEmbedder()
    return _DETECTOR, _EMBEDDER


def _best_face(detector, crop):
    """Best-scoring face across several scales: (score, bbox, factor) or None."""
    import cv2

    best = None
    for factor in SCALES:
        img = (crop if factor == 1.0 else
               cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC))
        try:
            scored = detector.detect_scored(img)
        except Exception:
            continue
        for box, score in scored or []:
            if best is None or score > best[0]:
                best = (float(score), box, factor, img)
    return best


def find_face(frame: np.ndarray, bbox, detector=None, embedder=None) -> Optional[dict]:
    """Look for one readable face inside a person box.

    Returns {"bbox": (x, y, w, h) in FRAME coords, "embedding": [...],
             "score": float, "scale": float, "face_jpeg": bytes} or None when
    there is no face to recover — the honest outcome for a distant or
    turned-away person. `face_jpeg` is the crop we found, so a human can look
    at it and say whether it really is a face before anything is stored.
    """
    import cv2

    crop = crop_person(frame, bbox)
    if crop is None:
        return None

    if detector is None:
        detector, _cached = _models()
        embedder = embedder or _cached

    best = _best_face(detector, crop)
    if best is None:
        return None
    score, (fx, fy, fw, fh), factor, scaled = best

    face_img = scaled[max(0, fy):fy + fh, max(0, fx):fx + fw]
    if face_img is None or face_img.size == 0:
        return None

    if embedder is None:
        _d, embedder = _models()
    emb = embedder.generate_embedding(face_img)
    if emb is None or len(emb) == 0:
        return None

    ok, buf = cv2.imencode(".jpg", face_img)

    # Map back: scaled-crop coords → crop coords → frame coords.
    x, y, w, h = (int(v) for v in bbox)
    p = int(max(w, h) * CROP_PAD)
    ox, oy = max(0, x - p), max(0, y - p)
    return {
        "bbox": (int(ox + fx / factor), int(oy + fy / factor),
                 int(fw / factor), int(fh / factor)),
        "embedding": [float(v) for v in np.asarray(emb).ravel()],
        "score": round(score, 3),
        "scale": factor,
        "face_jpeg": buf.tobytes() if ok else b"",
    }
