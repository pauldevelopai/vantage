"""
D-FINE object detector — Apache-2.0 replacement for YOLOv8n (AGPL).

WHY THIS EXISTS
---------------
The gatekeeper's default detector is Ultralytics YOLOv8n, which is licensed
AGPL-3.0. For a product that may be offered as a hosted/commercial service,
AGPL's network-copyleft is a liability (it would require releasing the whole
application's source, or buying an Ultralytics Enterprise License).

D-FINE (ICLR 2025) is a real-time DETR-based detector released under
Apache-2.0, distributed through Hugging Face Transformers. Swapping to it
removes the AGPL constraint entirely while keeping — and often improving —
detection accuracy per FLOP.

This detector produces the SAME `Detection` objects the gatekeeper's YOLO path
produces (class_id, class_name, confidence, bbox=(x,y,w,h), centroid), so it is
a drop-in for `VisionGatekeeper.detect_objects`.

Model selection
---------------
Default: ``ustc-community/dfine-nano-coco`` (smallest/fastest, CPU-friendly).
Override with the ``ALIBI_DFINE_MODEL`` env var, e.g.
``ustc-community/dfine-small-coco`` for higher accuracy.

If transformers/torch are not installed, importing/constructing this detector
raises ImportError; the gatekeeper catches that and falls back to YOLO.
"""

from __future__ import annotations

import os
from typing import List, Dict

import cv2
import numpy as np

# Detection is defined in gatekeeper; importing here is safe because the
# gatekeeper only imports THIS module lazily (inside its __init__), so by the
# time we run, the gatekeeper module is fully loaded.
from alibi.vision.gatekeeper import Detection

DEFAULT_DFINE_MODEL = os.getenv("ALIBI_DFINE_MODEL", "ustc-community/dfine-nano-coco")


class DFineDetector:
    """D-FINE object detector with a YOLO-compatible Detection output."""

    def __init__(self, model_id: str = DEFAULT_DFINE_MODEL, device: str = "cpu"):
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForObjectDetection
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "D-FINE needs transformers + torch. Install with:\n"
                "    pip install 'transformers>=4.48' torch timm\n"
                f"(original error: {e})"
            )

        self._torch = torch
        self.model_id = model_id
        self.device = device
        self.processor = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModelForObjectDetection.from_pretrained(model_id)
        self.model.to(device)
        self.model.eval()

        # {class_id: class_name} — mirrors ultralytics `model.names`.
        self.class_names: Dict[int, str] = {
            int(k): v for k, v in self.model.config.id2label.items()
        }

    def detect(self, frame: np.ndarray, conf_threshold: float = 0.25) -> List[Detection]:
        """
        Run D-FINE detection on a BGR frame and return Detection objects.

        Same contract as VisionGatekeeper.detect_objects (YOLO path).
        """
        if frame is None or frame.size == 0:
            return []

        # BGR (OpenCV) -> RGB for the image processor. cv2.cvtColor returns a
        # contiguous (positive-stride) array, which torch.from_numpy requires.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]

        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with self._torch.no_grad():
            outputs = self.model(**inputs)

        # (height, width) target for rescaling boxes to the original frame.
        target_sizes = self._torch.tensor([[h, w]])
        results = self.processor.post_process_object_detection(
            outputs, target_sizes=target_sizes, threshold=conf_threshold
        )[0]

        detections: List[Detection] = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            x1, y1, x2, y2 = [float(v) for v in box.tolist()]
            x, y = int(x1), int(y1)
            bw, bh = int(x2 - x1), int(y2 - y1)
            if bw <= 0 or bh <= 0:
                continue
            cls = int(label)
            detections.append(
                Detection(
                    class_id=cls,
                    class_name=self.class_names.get(cls, str(cls)),
                    confidence=float(score),
                    bbox=(x, y, bw, bh),
                    centroid=(x + bw / 2, y + bh / 2),
                )
            )
        return detections
