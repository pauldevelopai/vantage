"""
Hotlist Plate Detector

Detects license plates and matches against stolen vehicle hotlist.
ALWAYS requires human verification. NO automated impoundment.
"""

import cv2
import numpy as np
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import time

from alibi.video.detectors.base import Detector, DetectionResult
from alibi.video.zones import Zone
from alibi.plates import get_plate_detector, get_plate_ocr
from alibi.plates.normalize import normalize_plate
from alibi.plates.hotlist_store import HotlistStore


class HotlistPlateDetector(Detector):
    """
    Detects license plates and matches against hotlist.
    
    CRITICAL SAFETY RULES:
    - ALWAYS requires human verification
    - NEVER automated impoundment or arrest
    - ALWAYS uses "possible match" language
    - ALWAYS attaches evidence (plate crop + snapshot + clip)
    """
    
    def __init__(
        self,
        name: str = "hotlist_plate",
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Config options:
        - hotlist_path: Path to hotlist_plates.jsonl
        - ocr_confidence_threshold: Minimum OCR confidence (default 0.6)
        - check_interval_seconds: How often to check plates (default 2.0)
        - reload_interval_seconds: How often to reload hotlist (default 300)
        - evidence_dir: Directory for evidence files
        """
        super().__init__(name, config)
        
        # Configuration
        self.hotlist_path = self.config.get(
            'hotlist_path',
            'alibi/data/hotlist_plates.jsonl'
        )
        self.ocr_confidence_threshold = self.config.get('ocr_confidence_threshold', 0.6)
        self.check_interval = self.config.get('check_interval_seconds', 2.0)
        self.reload_interval = self.config.get('reload_interval_seconds', 300)
        self.evidence_dir = Path(self.config.get('evidence_dir', 'alibi/data/evidence'))
        
        # Initialize components
        self.plate_detector = get_plate_detector()
        self.plate_ocr = get_plate_ocr()
        self.hotlist_store = HotlistStore(self.hotlist_path)
        
        # State
        self.last_check_time = 0
        self.last_reload_time = 0
        self.frame_count = 0
        
        # Reload hotlist
        self._reload_hotlist()
    
    def _reload_hotlist(self):
        """Reload hotlist from storage"""
        try:
            # This will refresh the cache
            count = self.hotlist_store.count()
            self.last_reload_time = time.time()
            print(f"[HotlistPlateDetector] Loaded {count} hotlist entries")
        except Exception as e:
            print(f"[HotlistPlateDetector] Error loading hotlist: {e}")
    
    def detect(
        self,
        frame: np.ndarray,
        timestamp: float,
        camera_id: Optional[str] = None,
        zone: Optional[Zone] = None,
        **kwargs
    ) -> Optional[DetectionResult]:
        """
        Detect plates and check against hotlist.
        
        Args:
            frame: Input frame
            timestamp: Frame timestamp
            camera_id: Camera ID
            zone: Optional zone (not used for plate detection)
            
        Returns:
            DetectionResult if hotlist match found, None otherwise
        """
        if not self.enabled:
            return None
        
        self.frame_count += 1
        
        # Reload hotlist periodically
        if time.time() - self.last_reload_time > self.reload_interval:
            self._reload_hotlist()
        
        # Rate limiting: only check every N seconds
        if timestamp - self.last_check_time < self.check_interval:
            return None
        
        self.last_check_time = timestamp
        
        # Detect plates
        detected_plates = self.plate_detector.detect(frame, max_plates=3)
        
        if not detected_plates:
            return None
        
        # Process each detected plate
        for plate in detected_plates:
            # Run OCR
            try:
                plate_text, ocr_confidence = self.plate_ocr.read_plate(plate.plate_image)
                
                if not plate_text or ocr_confidence < self.ocr_confidence_threshold:
                    continue
                
                # Normalize plate
                normalized_plate = normalize_plate(plate_text)
                
                if not normalized_plate:
                    continue
                
                # Check against hotlist
                hotlist_entry = self.hotlist_store.get_by_plate(normalized_plate)
                
                if hotlist_entry:
                    # MATCH FOUND!
                    # Save plate crop
                    plate_crop_path = self._save_plate_crop(plate.plate_image, timestamp)
                    
                    # Calculate combined confidence
                    combined_confidence = min(plate.confidence, ocr_confidence)
                    
                    # Create detection result
                    return DetectionResult(
                        detected=True,
                        event_type="hotlist_plate_match",
                        confidence=combined_confidence,
                        severity=4,  # High severity - stolen vehicle
                        zone_id=zone.zone_id if zone else None,
                        metadata={
                            "plate_text": normalized_plate,
                            "ocr_confidence": round(ocr_confidence, 3),
                            "detection_confidence": round(plate.confidence, 3),
                            "combined_confidence": round(combined_confidence, 3),
                            "hotlist_reason": hotlist_entry.reason,
                            "hotlist_source": hotlist_entry.source_ref,
                            "plate_crop_url": f"/evidence/{plate_crop_path}" if plate_crop_path else None,
                            "bbox": {
                                "x": plate.bbox[0],
                                "y": plate.bbox[1],
                                "w": plate.bbox[2],
                                "h": plate.bbox[3]
                            },
                            "requires_verification": True,
                            "warning": "POSSIBLE HOTLIST PLATE MATCH - VERIFY"
                        }
                    )
            
            except Exception as e:
                print(f"[HotlistPlateDetector] Error processing plate: {e}")
                continue
        
        return None
    
    def _save_plate_crop(
        self,
        plate_image: np.ndarray,
        timestamp: float
    ) -> Optional[str]:
        """
        Save plate crop to evidence directory.
        
        Args:
            plate_image: Plate crop image
            timestamp: Detection timestamp
            
        Returns:
            Relative path for URL, or None if failed
        """
        try:
            # Create plate_crops subdirectory
            plate_crops_dir = self.evidence_dir / "plate_crops"
            plate_crops_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename
            dt = datetime.fromtimestamp(timestamp)
            filename = f"plate_{dt.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = plate_crops_dir / filename
            
            # Save with high quality
            cv2.imwrite(str(filepath), plate_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
            
            # Return relative path
            return f"plate_crops/{filename}"
        
        except Exception as e:
            print(f"[HotlistPlateDetector] Error saving plate crop: {e}")
            return None
    
    def reset(self):
        """Reset detector state"""
        self.last_check_time = 0
        self.frame_count = 0
        # Don't clear hotlist - keep in memory
