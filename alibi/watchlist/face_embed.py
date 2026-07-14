"""
Face Embedding Generator

Generates face embeddings for watchlist matching.

Backends (auto-selected, best first):
1. ArcFace (InsightFace, ONNX) — a real deep face-recognition model producing
   512-d embeddings. Same-person embeddings land close in cosine space,
   different people far apart — the accuracy a police watchlist needs.
   Enable with:  pip install insightface onnxruntime
2. face_recognition (dlib) — 128-d, decent, if installed.
3. "simple" (HOG features) — last-resort fallback. NOT reliable for identity;
   kept only so the pipeline never hard-fails.

The public interface (generate_embedding(bgr_crop) -> np.ndarray) is unchanged,
so face_match / watchlist_store work as-is. Embeddings within one store must
all come from the same backend (dims/space differ) — re-enroll if the backend
changes.
"""

import os

import cv2
import numpy as np
from typing import Optional, Tuple

# ArcFace recognition model. buffalo_l is accurate; buffalo_s is lighter.
DEFAULT_ARCFACE_PACK = os.getenv("VANTAGE_ARCFACE_MODEL", "buffalo_l")
_ARCFACE_REC_FILE = "w600k_r50.onnx"  # recognition model inside the pack


class FaceEmbedder:
    """
    Face embedding generator with a real ArcFace backend and graceful fallback.
    """

    def __init__(
        self,
        embedding_size: int = 128,
        face_size: Tuple[int, int] = (96, 96),
        arcface_pack: str = DEFAULT_ARCFACE_PACK,
    ):
        """
        Args:
            embedding_size: embedding length for the fallback methods (ArcFace
                is fixed at 512).
            face_size: resize target for the HOG fallback.
            arcface_pack: InsightFace model pack name.
        """
        self.embedding_size = embedding_size
        self.face_size = face_size
        self.arcface_pack = arcface_pack
        self._arcface = None
        self.face_recognition = None

        # 1) ArcFace (preferred)
        if self._init_arcface():
            self.method = "arcface"
            self.embedding_size = 512
            print(f"[FaceEmbedder] Using ArcFace / InsightFace ({arcface_pack}) — 512-d embeddings")
            return

        # 2) face_recognition (dlib)
        try:
            import face_recognition
            self.face_recognition = face_recognition
            self.method = "face_recognition"
            print("[FaceEmbedder] Using face_recognition library (dlib-based)")
            return
        except ImportError:
            pass

        # 3) simple HOG fallback
        self.method = "simple"
        print("[FaceEmbedder] WARNING: using simple HOG embedding — not reliable for identity. "
              "Install insightface for real face recognition: pip install insightface onnxruntime")

    def _init_arcface(self) -> bool:
        """Load the ArcFace recognition model (recognition only — no detector).
        Downloads the model pack on first use. Returns True on success."""
        try:
            import insightface
            home = os.path.expanduser("~/.insightface/models")
            rec_path = os.path.join(home, self.arcface_pack, _ARCFACE_REC_FILE)
            if not os.path.exists(rec_path):
                # Trigger the pack download (FaceAnalysis fetches + unzips it),
                # then load just the recognition model standalone.
                from insightface.app import FaceAnalysis
                FaceAnalysis(name=self.arcface_pack,
                             allowed_modules=["detection", "recognition"]).prepare(ctx_id=-1)
            rec = insightface.model_zoo.get_model(rec_path, providers=["CPUExecutionProvider"])
            rec.prepare(ctx_id=-1)
            self._arcface = rec
            return True
        except Exception as e:
            self._arcface = None
            print(f"[FaceEmbedder] ArcFace unavailable ({e}); falling back")
            return False

    def generate_embedding(self, face_image: np.ndarray) -> np.ndarray:
        """
        Generate a normalised embedding for a BGR face crop.

        Returns:
            L2-normalised embedding vector (512-d for ArcFace).
        """
        if self.method == "arcface":
            return self._generate_arcface(face_image)
        if self.method == "face_recognition":
            return self._generate_with_face_recognition(face_image)
        return self._generate_simple(face_image)

    def _generate_arcface(self, face_image: np.ndarray) -> np.ndarray:
        """ArcFace embedding: resize crop to 112x112, run the model, L2-normalise."""
        if face_image is None or getattr(face_image, "size", 0) == 0:
            return np.zeros(self.embedding_size, dtype=np.float32)
        crop = cv2.resize(face_image, (112, 112))
        feat = np.asarray(self._arcface.get_feat(crop), dtype=np.float32).ravel()
        norm = np.linalg.norm(feat)
        return (feat / norm if norm > 0 else feat).astype(np.float32)
    
    def _generate_with_face_recognition(self, face_image: np.ndarray) -> np.ndarray:
        """Generate embedding using face_recognition library"""
        # Convert BGR to RGB
        rgb_image = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
        
        # Generate encoding (128-d vector)
        encodings = self.face_recognition.face_encodings(rgb_image)
        
        if len(encodings) == 0:
            # Fall back to simple method if no face detected
            print("[FaceEmbedder] Warning: No face detected by face_recognition, using simple method")
            return self._generate_simple(face_image)
        
        # Return first encoding
        embedding = encodings[0]
        
        # Normalize
        embedding = embedding / (np.linalg.norm(embedding) + 1e-7)
        
        return embedding.astype(np.float32)
    
    def _generate_simple(self, face_image: np.ndarray) -> np.ndarray:
        """
        Generate simple embedding (fallback method).
        
        This is a basic approach for when face_recognition is not available.
        Uses HOG (Histogram of Oriented Gradients) features.
        """
        # Resize to fixed size
        resized = cv2.resize(face_image, self.face_size)
        
        # Convert to grayscale
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        
        # Apply histogram equalization
        gray = cv2.equalizeHist(gray)
        
        # Calculate HOG features
        win_size = self.face_size
        block_size = (16, 16)
        block_stride = (8, 8)
        cell_size = (8, 8)
        nbins = 9
        
        hog = cv2.HOGDescriptor(
            win_size,
            block_size,
            block_stride,
            cell_size,
            nbins
        )
        
        features = hog.compute(gray)
        
        # Flatten and normalize
        embedding = features.flatten()
        
        # Reduce dimensionality if needed
        if len(embedding) > self.embedding_size:
            # Simple dimensionality reduction: average pooling
            factor = len(embedding) // self.embedding_size
            embedding = embedding[:self.embedding_size * factor].reshape(self.embedding_size, factor).mean(axis=1)
        elif len(embedding) < self.embedding_size:
            # Pad with zeros
            embedding = np.pad(embedding, (0, self.embedding_size - len(embedding)))
        
        # Normalize to unit length
        embedding = embedding / (np.linalg.norm(embedding) + 1e-7)
        
        return embedding.astype(np.float32)
