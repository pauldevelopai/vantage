"""
FastALPR Engine — drop-in replacement for the OpenCV-contour PlateDetector
and EasyOCR-based PlateOCR.

WHY:
- The legacy `plate_detect.PlateDetector` finds plate regions with hand-tuned
  edge/contour/aspect-ratio heuristics. That is brittle on real CCTV (angles,
  glare, motion blur, night).
- The legacy `plate_ocr.PlateOCR` uses EasyOCR, a generic scene-text engine,
  which mis-reads skewed / low-res plates.

This module swaps both for the FastALPR stack:
- Detection: open-image-models (YOLO-v9 ONNX, trained specifically on plates)
- OCR:       fast-plate-ocr (CCT models trained specifically on plate text)

Both ship as ONNX weights (MIT licensed) — NO runtime dependency on the
AGPL `ultralytics` package.

The public classes below expose the SAME interface as the legacy modules:
    detector = PlateDetector()
    ocr = PlateOCR()
    plates = detector.detect(frame, max_plates=3)   # -> List[DetectedPlate]
    for p in plates:
        text, conf = ocr.read_plate(p.plate_image)   # -> (str, float)

So existing callers (mobile_camera_enhanced, hotlist_plate_detector,
plate_vehicle_mismatch_detector) work unchanged — only the import swaps.

Graceful degradation: if fast-alpr is not installed, importing this module
raises ImportError with install instructions; callers can fall back to the
legacy engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

try:
    from open_image_models import LicensePlateDetector
    from fast_plate_ocr import LicensePlateRecognizer
    FAST_ALPR_AVAILABLE = True
except ImportError as _e:  # pragma: no cover
    FAST_ALPR_AVAILABLE = False
    _IMPORT_ERROR = _e


# Default models. Both are downloaded once from the model hub and cached.
#   - yolo-v9-t-384: "tiny" detector, good speed/accuracy on CPU.
#   - cct-xs-v2-global-model: extra-small global OCR (handles most regions).
DEFAULT_DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"
DEFAULT_OCR_MODEL = "cct-xs-v2-global-model"


@dataclass
class DetectedPlate:
    """
    A detected license plate region.

    Interface-compatible with alibi.plates.plate_detect.DetectedPlate:
    exposes .bbox (x, y, w, h), .confidence, .plate_image (BGR crop) and
    .get_crop(). Adds .ocr_text / .ocr_confidence, populated when the plate
    was produced by the combined FastALPR pipeline (harmless extra fields
    that legacy callers ignore).
    """

    bbox: Tuple[int, int, int, int]  # (x, y, w, h) — matches legacy contract
    confidence: float                # detector confidence 0.0-1.0
    plate_image: np.ndarray          # cropped plate region (BGR)
    ocr_text: Optional[str] = None
    ocr_confidence: Optional[float] = None

    def get_crop(self, padding: float = 0.1) -> np.ndarray:
        """Return the plate crop (padding kept for signature compatibility)."""
        return self.plate_image


def _require_available() -> None:
    if not FAST_ALPR_AVAILABLE:
        raise ImportError(
            "fast-alpr is not installed. Install with:\n"
            "    pip install fast-alpr onnxruntime\n"
            f"(original import error: {_IMPORT_ERROR})"
        )


class PlateDetector:
    """
    Trained-model plate detector (open-image-models / YOLO-v9 ONNX).

    Drop-in for alibi.plates.plate_detect.PlateDetector — same .detect()
    signature and DetectedPlate output shape. The constructor accepts the
    legacy heuristic kwargs and ignores them (kept so existing call sites
    that pass aspect-ratio/area tuning don't break).
    """

    def __init__(
        self,
        detection_model: str = DEFAULT_DETECTOR_MODEL,
        conf_thresh: float = 0.25,
        # --- legacy kwargs, accepted and ignored for compatibility ---
        min_aspect_ratio: float = None,
        max_aspect_ratio: float = None,
        min_area: int = None,
        max_area: int = None,
    ):
        _require_available()
        self.conf_thresh = conf_thresh
        self._model = LicensePlateDetector(
            detection_model=detection_model,
            conf_thresh=conf_thresh,
        )

    def detect(self, frame: np.ndarray, max_plates: int = 3) -> List[DetectedPlate]:
        """
        Detect license plate regions in a BGR frame.

        Returns up to `max_plates` DetectedPlate objects, highest-confidence
        first — same contract as the legacy contour detector.
        """
        if frame is None or frame.size == 0:
            return []

        results = self._model.predict(frame)
        h, w = frame.shape[:2]

        plates: List[DetectedPlate] = []
        for det in results:
            bb = det.bounding_box
            # Clamp to frame bounds; guard against degenerate boxes.
            x1 = max(0, int(bb.x1))
            y1 = max(0, int(bb.y1))
            x2 = min(w, int(bb.x2))
            y2 = min(h, int(bb.y2))
            if x2 <= x1 or y2 <= y1:
                continue

            crop = frame[y1:y2, x1:x2].copy()
            plates.append(
                DetectedPlate(
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    confidence=float(det.confidence),
                    plate_image=crop,
                )
            )

        plates.sort(key=lambda p: p.confidence, reverse=True)
        return plates[:max_plates]


class PlateOCR:
    """
    Trained plate OCR (fast-plate-ocr / CCT ONNX).

    Drop-in for alibi.plates.plate_ocr.PlateOCR — same .read_plate() contract:
    accepts a BGR plate crop, returns (plate_text, confidence).
    """

    def __init__(self, ocr_model: str = DEFAULT_OCR_MODEL):
        _require_available()
        self.ocr_type = "fast-plate-ocr"
        self._model = LicensePlateRecognizer(hub_ocr_model=ocr_model, device="auto")

    def read_plate(self, plate_image: np.ndarray) -> Tuple[str, float]:
        """
        Read plate text from a cropped plate image (BGR).

        Returns (text, confidence). Confidence is the mean per-character
        probability from the OCR model (0.0-1.0), so downstream thresholds
        that compared against EasyOCR confidence keep working.
        """
        if plate_image is None or plate_image.size == 0:
            return "", 0.0

        pred = self._model.run_one(plate_image, return_confidence=True)

        text = (pred.plate or "").strip()
        if pred.char_probs is not None and len(pred.char_probs) > 0:
            confidence = float(np.mean(pred.char_probs))
        else:
            confidence = 0.0 if not text else 1.0

        return text, confidence
