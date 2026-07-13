"""
Watchlist Detector

Detects faces and matches against City Police watchlist.
ALWAYS requires human verification. NEVER claims identity.
"""

import cv2
import numpy as np
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from alibi.video.detectors.base import Detector, DetectionResult
from alibi.video.zones import Zone
from alibi.watchlist.face_detect import FaceDetector
from alibi.watchlist.face_embed import FaceEmbedder
from alibi.watchlist.face_match import FaceMatcher
from alibi.watchlist.watchlist_store import WatchlistStore


class WatchlistDetector(Detector):
    """
    Detects faces and matches against watchlist.
    
    CRITICAL SAFETY RULES:
    - ALWAYS requires human verification
    - NEVER claims identity as fact
    - ALWAYS uses "possible match" language
    - ALWAYS attaches evidence (face crop + snapshot + clip)
    """
    
    def __init__(
        self,
        name: str = "watchlist",
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Config options:
        - watchlist_path: Path to watchlist.jsonl (default: alibi/data/watchlist.jsonl)
        - match_threshold: Minimum similarity for match (default 0.6)
        - face_confidence: Minimum face detection confidence (default 0.5)
        - check_interval_seconds: How often to check faces (default 5.0)
        - reload_interval_seconds: How often to reload watchlist (default 300)
        - evidence_dir: Directory for face crops (default: alibi/data/evidence)
        - top_k_candidates: Number of top matches to return (default 3)
        """
        super().__init__(name, config)
        
        # Configuration
        self.watchlist_path = self.config.get(
            'watchlist_path',
            'alibi/data/watchlist.jsonl'
        )
        self.match_threshold = self.config.get('match_threshold', 0.6)
        self.face_confidence = self.config.get('face_confidence', 0.5)
        self.check_interval = self.config.get('check_interval_seconds', 5.0)
        self.reload_interval = self.config.get('reload_interval_seconds', 300)
        self.evidence_dir = Path(self.config.get('evidence_dir', 'alibi/data/evidence'))
        self.top_k = self.config.get('top_k_candidates', 3)
        
        # Initialize components
        self.face_detector = FaceDetector(confidence_threshold=self.face_confidence)
        self.face_embedder = FaceEmbedder()
        self.face_matcher = FaceMatcher(
            match_threshold=self.match_threshold,
            top_k=self.top_k
        )
        
        # State
        self.watchlist_embeddings: Dict[str, np.ndarray] = {}
        self.watchlist_labels: Dict[str, str] = {}
        self.last_check_time = 0
        self.last_reload_time = 0
        self.frame_count = 0
        
        # Load watchlist
        self._reload_watchlist()
    
    def _reload_watchlist(self):
        """Reload watchlist from storage"""
        try:
            store = WatchlistStore(self.watchlist_path)
            entries = store.load_all()
            
            # Build embedding and label dictionaries
            self.watchlist_embeddings.clear()
            self.watchlist_labels.clear()
            
            for entry in entries:
                self.watchlist_embeddings[entry.person_id] = entry.get_embedding_array()
                self.watchlist_labels[entry.person_id] = entry.label
            
            self.last_reload_time = time.time()
            
            print(f"[WatchlistDetector] Loaded {len(entries)} watchlist entries")
        
        except Exception as e:
            print(f"[WatchlistDetector] Error loading watchlist: {e}")
    
    def detect(
        self,
        frame: np.ndarray,
        timestamp: float,
        zone: Optional[Zone] = None,
        **kwargs
    ) -> Optional[DetectionResult]:
        """
        Detect faces and match against watchlist.
        
        Args:
            frame: Input frame
            timestamp: Frame timestamp
            zone: Optional zone (not used for watchlist)
        
        Returns:
            DetectionResult if match found, None otherwise
        """
        if not self.enabled:
            return None
        
        self.frame_count += 1
        
        # Reload watchlist periodically
        if time.time() - self.last_reload_time > self.reload_interval:
            self._reload_watchlist()
        
        # Check if watchlist is empty
        if not self.watchlist_embeddings:
            return None  # No watchlist entries to match against
        
        # Rate limiting: only check every N seconds
        if timestamp - self.last_check_time < self.check_interval:
            return None
        
        self.last_check_time = timestamp
        
        # Detect faces
        faces = self.face_detector.detect(frame)
        
        if not faces:
            return None  # No faces detected
        
        # Process each face
        for face_bbox in faces:
            # Extract face crop
            face_crop = self.face_detector.extract_face(frame, face_bbox)
            
            if face_crop.size == 0:
                continue
            
            # Generate embedding
            try:
                embedding = self.face_embedder.generate_embedding(face_crop)
            except Exception as e:
                print(f"[WatchlistDetector] Error generating embedding: {e}")
                continue
            
            # Match against watchlist
            is_match, candidates, best_score = self.face_matcher.match(
                embedding,
                self.watchlist_embeddings,
                self.watchlist_labels
            )
            
            if is_match:
                # Save face crop for evidence
                face_crop_path = self._save_face_crop(face_crop, timestamp)
                
                # Create detection result
                return DetectionResult(
                    detected=True,
                    event_type="watchlist_match",
                    confidence=best_score,
                    severity=4,  # High severity - requires immediate review
                    zone_id=zone.zone_id if zone else None,
                    metadata={
                        "match_score": round(best_score, 4),
                        "top_candidates": [c.to_dict() for c in candidates],
                        "face_bbox": {
                            "x": face_bbox[0],
                            "y": face_bbox[1],
                            "w": face_bbox[2],
                            "h": face_bbox[3]
                        },
                        "face_crop_url": f"/evidence/{face_crop_path}" if face_crop_path else None,
                        "detection_method": self.face_embedder.method,
                        "requires_verification": True,
                        "warning": "POSSIBLE MATCH - HUMAN VERIFICATION REQUIRED"
                    }
                )
        
        return None  # No matches above threshold
    
    def _save_face_crop(
        self,
        face_crop: np.ndarray,
        timestamp: float
    ) -> Optional[str]:
        """
        Save face crop to evidence directory.
        
        Args:
            face_crop: Face crop image
            timestamp: Detection timestamp
            
        Returns:
            Relative path for URL, or None if failed
        """
        try:
            # Create face_crops subdirectory
            face_crops_dir = self.evidence_dir / "face_crops"
            face_crops_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename
            dt = datetime.fromtimestamp(timestamp)
            filename = f"face_{dt.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = face_crops_dir / filename
            
            # Save with high quality
            cv2.imwrite(str(filepath), face_crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            
            # Return relative path
            return f"face_crops/{filename}"
        
        except Exception as e:
            print(f"[WatchlistDetector] Error saving face crop: {e}")
            return None
    
    def reset(self):
        """Reset detector state"""
        self.last_check_time = 0
        self.frame_count = 0
        # Don't clear watchlist - keep in memory


def main():
    """CLI entry point"""
    from alibi.watchlist.enroll import enroll_face
    
    parser = argparse.ArgumentParser(
        description="Enroll face into Vantage watchlist"
    )
    
    parser.add_argument(
        '--person_id',
        required=True,
        help='Unique identifier'
    )
    
    parser.add_argument(
        '--label',
        required=True,
        help='Name/alias'
    )
    
    parser.add_argument(
        '--image',
        required=True,
        help='Path to face image'
    )
    
    parser.add_argument(
        '--source',
        default='',
        help='Source reference'
    )
    
    parser.add_argument(
        '--watchlist',
        default='alibi/data/watchlist.jsonl',
        help='Watchlist file path'
    )
    
    args = parser.parse_args()
    
    success = enroll_face(
        person_id=args.person_id,
        label=args.label,
        image_path=args.image,
        source_ref=args.source,
        watchlist_path=args.watchlist
    )
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
