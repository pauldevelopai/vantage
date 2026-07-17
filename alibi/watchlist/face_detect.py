"""
Face Detection

Detects faces in frames. Primary backend is InsightFace SCRFD (ONNX, via
onnxruntime) — accurate, and it does NOT depend on the legacy OpenCV APIs
(cv2.dnn.readNetFromCaffe, cv2.CascadeClassifier) that OpenCV 5.0 removed.
Falls back to those OpenCV detectors only where they still exist.
"""

import os

import cv2
import numpy as np
from typing import List, Tuple, Optional
from pathlib import Path

# SCRFD detector lives in the same InsightFace pack as the ArcFace recogniser.
DEFAULT_ARCFACE_PACK = os.getenv("VANTAGE_ARCFACE_MODEL", "buffalo_l")
_SCRFD_FILE = "det_10g.onnx"


class FaceDetector:
    """Face detector: InsightFace SCRFD primary, OpenCV DNN/Haar fallback."""

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        model_path: Optional[str] = None,
        arcface_pack: str = DEFAULT_ARCFACE_PACK,
    ):
        """
        Args:
            confidence_threshold: Minimum confidence for detection.
            model_path: Optional path (unused by the SCRFD backend).
            arcface_pack: InsightFace pack that holds the SCRFD model.
        """
        self.confidence_threshold = confidence_threshold
        self.arcface_pack = arcface_pack
        self._scrfd = None
        self.net = None
        self.face_cascade = None

        # 1) InsightFace SCRFD (preferred, OpenCV-5 safe)
        if self._init_scrfd():
            self.method = "scrfd"
            print("[FaceDetector] Using InsightFace SCRFD face detector")
            return

        # 2) OpenCV DNN (Caffe) — only if this OpenCV build still has it
        try:
            if hasattr(cv2, "dnn") and hasattr(cv2.dnn, "readNetFromCaffe"):
                prototxt = cv2.data.haarcascades + "../deploy.prototxt"
                model = cv2.data.haarcascades + "../res10_300x300_ssd_iter_140000.caffemodel"
                self.net = cv2.dnn.readNetFromCaffe(prototxt, model)
                self.method = "dnn"
                print("[FaceDetector] Using OpenCV DNN face detector")
                return
        except Exception:
            self.net = None

        # 3) Haar cascade — only if this OpenCV build still has it
        try:
            if hasattr(cv2, "CascadeClassifier"):
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
                self.method = "haar"
                print("[FaceDetector] Using Haar Cascade face detector")
                return
        except Exception:
            self.face_cascade = None

        # 4) Nothing available — detect() returns [] instead of crashing
        self.method = "none"
        print("[FaceDetector] WARNING: no face detector available. "
              "Install insightface for detection: pip install insightface onnxruntime")

    def _init_scrfd(self) -> bool:
        """Load the SCRFD detection model (downloads the pack on first use)."""
        try:
            import insightface
            home = os.path.expanduser("~/.insightface/models")
            det_path = os.path.join(home, self.arcface_pack, _SCRFD_FILE)
            if not os.path.exists(det_path):
                from insightface.app import FaceAnalysis
                FaceAnalysis(name=self.arcface_pack,
                             allowed_modules=["detection", "recognition"]).prepare(ctx_id=-1)
            det = insightface.model_zoo.get_model(det_path, providers=["CPUExecutionProvider"])
            det.prepare(ctx_id=-1, input_size=(640, 640))
            det.det_thresh = self.confidence_threshold  # SCRFD threshold is an attribute
            self._scrfd = det
            return True
        except Exception as e:
            self._scrfd = None
            print(f"[FaceDetector] SCRFD unavailable ({e}); falling back")
            return False

    def detect(self, image: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detect faces in a BGR image.

        Returns:
            List of bounding boxes [(x, y, w, h), ...].
        """
        return [bbox for bbox, _score in self.detect_scored(image)]

    def detect_scored(self, image: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """Detect faces with their detector confidence: [((x, y, w, h), score)].
        Only the SCRFD backend has a real score; the fallbacks report their own
        threshold (they filtered on it internally)."""
        if image is None or getattr(image, "size", 0) == 0:
            return []
        if self.method == "scrfd":
            return self._detect_scrfd(image)
        if self.method == "dnn":
            return [(b, self.confidence_threshold) for b in self._detect_dnn(image)]
        if self.method == "haar":
            return [(b, self.confidence_threshold) for b in self._detect_haar(image)]
        return []

    def _detect_scrfd(self, image: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """Detect using InsightFace SCRFD; returns ((x, y, w, h), score) pairs."""
        h, w = image.shape[:2]
        bboxes, _kpss = self._scrfd.detect(image, metric="default")
        faces = []
        for det in bboxes:
            x1, y1, x2, y2 = det[:4]
            score = float(det[4]) if len(det) > 4 else self.confidence_threshold
            x = max(0, int(x1)); y = max(0, int(y1))
            bw = min(w - x, int(x2 - x1)); bh = min(h - y, int(y2 - y1))
            if bw > 0 and bh > 0:
                faces.append(((x, y, bw, bh), score))
        return faces
    
    def _detect_dnn(self, image: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Detect using DNN"""
        h, w = image.shape[:2]
        
        # Prepare blob
        blob = cv2.dnn.blobFromImage(
            cv2.resize(image, (300, 300)),
            1.0,
            (300, 300),
            (104.0, 177.0, 123.0)
        )
        
        # Forward pass
        self.net.setInput(blob)
        detections = self.net.forward()
        
        # Extract bounding boxes
        faces = []
        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            
            if confidence > self.confidence_threshold:
                # Get bounding box
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                x1, y1, x2, y2 = box.astype(int)
                
                # Convert to (x, y, w, h) format
                x = max(0, x1)
                y = max(0, y1)
                width = min(w - x, x2 - x1)
                height = min(h - y, y2 - y1)
                
                faces.append((x, y, width, height))
        
        return faces
    
    def _detect_haar(self, image: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Detect using Haar Cascades"""
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )
        
        # Convert to list of tuples
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]
    
    def extract_face(
        self,
        image: np.ndarray,
        bbox: Tuple[int, int, int, int],
        padding: float = 0.2
    ) -> np.ndarray:
        """
        Extract face region from image with padding.
        
        Args:
            image: Input image
            bbox: Bounding box (x, y, w, h)
            padding: Padding ratio (0.2 = 20% padding)
            
        Returns:
            Face crop image
        """
        x, y, w, h = bbox
        
        # Add padding
        pad_w = int(w * padding)
        pad_h = int(h * padding)
        
        x1 = max(0, x - pad_w)
        y1 = max(0, y - pad_h)
        x2 = min(image.shape[1], x + w + pad_w)
        y2 = min(image.shape[0], y + h + pad_h)
        
        # Extract face
        face = image[y1:y2, x1:x2]
        
        return face
    
    def detect_and_extract(
        self,
        image: np.ndarray,
        return_largest: bool = True
    ) -> Optional[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
        """
        Detect faces and extract the largest one.
        
        Args:
            image: Input image
            return_largest: Return largest face only
            
        Returns:
            Tuple of (face_crop, bbox) or None if no face detected
        """
        faces = self.detect(image)
        
        if not faces:
            return None
        
        if return_largest:
            # Get largest face by area
            largest = max(faces, key=lambda f: f[2] * f[3])
            face_crop = self.extract_face(image, largest)
            return face_crop, largest
        else:
            # Return first face
            face_crop = self.extract_face(image, faces[0])
            return face_crop, faces[0]
