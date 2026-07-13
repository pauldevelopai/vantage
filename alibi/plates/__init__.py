"""
Vantage License Plate Recognition System

Hotlist plate detection and matching.
ALWAYS requires human verification. NO automated impoundment.

Engine selection
----------------
Two ALPR backends are available with identical interfaces:

- FastALPR (trained ONNX detector + OCR) — preferred. Trained plate models,
  MIT licensed, no AGPL `ultralytics` runtime dependency.
- Legacy (OpenCV-contour detector + EasyOCR) — original fallback.

Call ``get_plate_detector()`` / ``get_plate_ocr()`` instead of constructing a
class directly. They return FastALPR when it is installed and importable, and
fall back to the legacy engine otherwise. Set ``ALIBI_DISABLE_FAST_ALPR=1`` to
force the legacy engine.
"""

import os

from alibi.plates.plate_detect import PlateDetector, DetectedPlate
from alibi.plates.plate_ocr import PlateOCR
from alibi.plates.normalize import normalize_plate, is_valid_namibia_plate
from alibi.plates.hotlist_store import HotlistStore, HotlistEntry


def _fast_alpr_enabled() -> bool:
    """True if FastALPR is available and not disabled via env."""
    if os.getenv("ALIBI_DISABLE_FAST_ALPR", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        import open_image_models  # noqa: F401
        import fast_plate_ocr  # noqa: F401
        return True
    except ImportError:
        return False


def get_plate_detector(**kwargs):
    """
    Return a plate detector: FastALPR (trained ONNX) if available, else the
    legacy OpenCV-contour detector. Same ``.detect(frame, max_plates)`` API.
    """
    if _fast_alpr_enabled():
        try:
            from alibi.plates.fast_alpr_engine import PlateDetector as FastDetector
            return FastDetector(**kwargs)
        except Exception as e:  # pragma: no cover - defensive fallback
            print(f"[plates] FastALPR detector unavailable ({e}); "
                  f"falling back to legacy contour detector")
    return PlateDetector(**kwargs)


def get_plate_ocr(**kwargs):
    """
    Return a plate OCR engine: FastALPR (trained CCT) if available, else the
    legacy EasyOCR/Tesseract engine. Same ``.read_plate(crop)`` API.
    """
    if _fast_alpr_enabled():
        try:
            from alibi.plates.fast_alpr_engine import PlateOCR as FastOCR
            return FastOCR(**kwargs)
        except Exception as e:  # pragma: no cover - defensive fallback
            print(f"[plates] FastALPR OCR unavailable ({e}); "
                  f"falling back to legacy EasyOCR")
    return PlateOCR(**kwargs)


__all__ = [
    'PlateDetector',
    'DetectedPlate',
    'PlateOCR',
    'get_plate_detector',
    'get_plate_ocr',
    'normalize_plate',
    'is_valid_namibia_plate',
    'HotlistStore',
    'HotlistEntry',
]
