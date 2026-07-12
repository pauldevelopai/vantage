"""
Plate-Vehicle Mismatch Detector

Detects mismatches between observed license plates and vehicle make/model.
Requires BOTH plate reading AND vehicle classification to be functional.
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
from alibi.vehicles.vehicle_detect import VehicleDetector
from alibi.vehicles.vehicle_attrs import VehicleAttributeExtractor
from alibi.vehicles.plate_registry import PlateRegistryStore
from alibi.vehicles.mismatch import check_mismatch


class PlateVehicleMismatchDetector(Detector):
    """
    Detects mismatches between plate and vehicle attributes.
    
    Conservative approach:
    - Only runs when BOTH plate AND make/model are available
    - Only alerts when confidence exceeds thresholds
    - Never alerts on "unknown" make/model
    - Requires human verification
    """
    
    def __init__(
        self,
        name: str = "plate_vehicle_mismatch",
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Config options:
        - check_interval_seconds: How often to check (default 5.0)
        - plate_confidence_threshold: Min plate OCR confidence (default 0.7)
        - vehicle_confidence_threshold: Min vehicle attr confidence (default 0.5)
        - mismatch_min_score: Min mismatch score to alert (default 0.3)
        - registry_path: Path to plate registry JSONL
        - evidence_dir: Directory for evidence files
        """
        super().__init__(name, config)
        
        # Configuration
        self.check_interval = self.config.get('check_interval_seconds', 5.0)
        self.plate_confidence_threshold = self.config.get('plate_confidence_threshold', 0.7)
        self.vehicle_confidence_threshold = self.config.get('vehicle_confidence_threshold', 0.5)
        self.mismatch_min_score = self.config.get('mismatch_min_score', 0.3)
        self.registry_path = self.config.get('registry_path', 'alibi/data/plate_registry.jsonl')
        self.evidence_dir = Path(self.config.get('evidence_dir', 'alibi/data/evidence'))
        
        # Initialize components
        self.plate_detector = get_plate_detector()
        self.plate_ocr = get_plate_ocr()
        self.vehicle_detector = VehicleDetector()
        self.attr_extractor = VehicleAttributeExtractor()
        self.registry_store = PlateRegistryStore(self.registry_path)
        
        # State
        self.last_check_time = 0
        self.frame_count = 0
        
        print(f"[PlateVehicleMismatchDetector] Initialized - mismatch detection active")
        print(f"  Plate confidence threshold: {self.plate_confidence_threshold}")
        print(f"  Vehicle confidence threshold: {self.vehicle_confidence_threshold}")
        print(f"  Mismatch score threshold: {self.mismatch_min_score}")
    
    def detect(
        self,
        frame: np.ndarray,
        timestamp: float,
        camera_id: Optional[str] = None,
        zone: Optional[Zone] = None,
        **kwargs
    ) -> Optional[DetectionResult]:
        """
        Detect plate-vehicle mismatches.
        
        Args:
            frame: Input frame
            timestamp: Frame timestamp
            camera_id: Camera ID
            zone: Optional zone
            
        Returns:
            DetectionResult if mismatch detected
        """
        if not self.enabled:
            return None
        
        self.frame_count += 1
        
        # Rate limiting
        if timestamp - self.last_check_time < self.check_interval:
            return None
        
        self.last_check_time = timestamp
        
        try:
            # Step 1: Detect and read plate
            plate_detections = self.plate_detector.detect(frame)
            
            if not plate_detections:
                return None
            
            # Use first plate detection
            plate_detection = plate_detections[0]
            
            # OCR the plate
            plate_text, plate_confidence = self.plate_ocr.read_plate(plate_detection.plate_crop)
            
            if not plate_text or plate_confidence < self.plate_confidence_threshold:
                return None
            
            # Normalize plate
            normalized_plate = normalize_plate(plate_text)
            
            if not normalized_plate:
                return None
            
            # Step 2: Check if plate is in registry
            registry_entry = self.registry_store.get_by_plate(normalized_plate)
            
            if not registry_entry:
                # Not in registry - no mismatch check needed
                return None
            
            # Step 3: Detect and classify vehicle
            vehicle_detections = self.vehicle_detector.detect(frame, max_vehicles=1)
            
            if not vehicle_detections:
                return None
            
            # Use first vehicle detection
            vehicle_detection = vehicle_detections[0]
            
            # Extract attributes
            vehicle_attrs = self.attr_extractor.extract_attributes(vehicle_detection.vehicle_crop)
            
            # Step 4: Check for mismatch
            mismatch_result = check_mismatch(
                plate_text=normalized_plate,
                expected_make=registry_entry.expected_make,
                expected_model=registry_entry.expected_model,
                observed_make=vehicle_attrs.make,
                observed_model=vehicle_attrs.model,
                observed_make_confidence=vehicle_attrs.make_model_confidence,
                observed_model_confidence=vehicle_attrs.make_model_confidence,
                min_confidence=self.vehicle_confidence_threshold,
                min_score=self.mismatch_min_score
            )
            
            if not mismatch_result:
                # No mismatch or confidence too low
                return None
            
            # Step 5: Save evidence
            plate_crop_path = self._save_plate_crop(plate_detection.plate_crop, timestamp)
            vehicle_crop_path = self._save_vehicle_crop(vehicle_detection.vehicle_crop, timestamp)
            annotated_snapshot_path = self._save_annotated_snapshot(
                frame,
                plate_detection.bbox,
                vehicle_detection.bbox,
                timestamp,
                mismatch_result
            )
            
            # Step 6: Emit mismatch event
            return DetectionResult(
                detected=True,
                event_type="plate_vehicle_mismatch",
                confidence=mismatch_result.mismatch_score,
                severity=4,  # High severity - requires verification
                zone_id=zone.zone_id if zone else None,
                metadata={
                    "plate_text": normalized_plate,
                    "plate_confidence": round(plate_confidence, 3),
                    "expected_make": mismatch_result.expected_make,
                    "expected_model": mismatch_result.expected_model,
                    "observed_make": mismatch_result.observed_make,
                    "observed_model": mismatch_result.observed_model,
                    "observed_confidence": round(vehicle_attrs.make_model_confidence, 3),
                    "mismatch_score": round(mismatch_result.mismatch_score, 3),
                    "explanation": mismatch_result.explanation,
                    "plate_bbox": list(plate_detection.bbox),
                    "vehicle_bbox": list(vehicle_detection.bbox),
                    "plate_crop_url": f"/evidence/{plate_crop_path}" if plate_crop_path else None,
                    "vehicle_crop_url": f"/evidence/{vehicle_crop_path}" if vehicle_crop_path else None,
                    "annotated_snapshot_url": f"/evidence/{annotated_snapshot_path}" if annotated_snapshot_path else None,
                }
            )
        
        except Exception as e:
            print(f"[PlateVehicleMismatchDetector] Error: {e}")
            return None
    
    def _save_plate_crop(self, plate_crop: np.ndarray, timestamp: float) -> Optional[str]:
        """Save plate crop"""
        try:
            crops_dir = self.evidence_dir / "mismatch_plate_crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            
            dt = datetime.fromtimestamp(timestamp)
            filename = f"plate_{dt.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = crops_dir / filename
            
            cv2.imwrite(str(filepath), plate_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            
            return f"mismatch_plate_crops/{filename}"
        
        except Exception as e:
            print(f"[PlateVehicleMismatchDetector] Error saving plate crop: {e}")
            return None
    
    def _save_vehicle_crop(self, vehicle_crop: np.ndarray, timestamp: float) -> Optional[str]:
        """Save vehicle crop"""
        try:
            crops_dir = self.evidence_dir / "mismatch_vehicle_crops"
            crops_dir.mkdir(parents=True, exist_ok=True)
            
            dt = datetime.fromtimestamp(timestamp)
            filename = f"vehicle_{dt.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = crops_dir / filename
            
            cv2.imwrite(str(filepath), vehicle_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            
            return f"mismatch_vehicle_crops/{filename}"
        
        except Exception as e:
            print(f"[PlateVehicleMismatchDetector] Error saving vehicle crop: {e}")
            return None
    
    def _save_annotated_snapshot(
        self,
        frame: np.ndarray,
        plate_bbox: tuple,
        vehicle_bbox: tuple,
        timestamp: float,
        mismatch_result
    ) -> Optional[str]:
        """Save annotated snapshot showing both plate and vehicle"""
        try:
            snapshots_dir = self.evidence_dir / "mismatch_snapshots"
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            
            # Create annotated frame
            annotated = frame.copy()
            
            # Draw plate bbox (red)
            px, py, pw, ph = [int(c) for c in plate_bbox]
            cv2.rectangle(annotated, (px, py), (px+pw, py+ph), (0, 0, 255), 2)
            cv2.putText(annotated, f"Plate: {mismatch_result.plate_text}", 
                       (px, py-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
            # Draw vehicle bbox (orange)
            vx, vy, vw, vh = [int(c) for c in vehicle_bbox]
            cv2.rectangle(annotated, (vx, vy), (vx+vw, vy+vh), (0, 165, 255), 2)
            cv2.putText(annotated, f"Vehicle: {mismatch_result.observed_make} {mismatch_result.observed_model}", 
                       (vx, vy-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)
            
            # Add mismatch warning text
            cv2.putText(annotated, "POSSIBLE MISMATCH - VERIFY", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            cv2.putText(annotated, f"Expected: {mismatch_result.expected_make} {mismatch_result.expected_model}", 
                       (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(annotated, f"Observed: {mismatch_result.observed_make} {mismatch_result.observed_model}", 
                       (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Save
            dt = datetime.fromtimestamp(timestamp)
            filename = f"mismatch_{dt.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = snapshots_dir / filename
            
            cv2.imwrite(str(filepath), annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
            
            return f"mismatch_snapshots/{filename}"
        
        except Exception as e:
            print(f"[PlateVehicleMismatchDetector] Error saving annotated snapshot: {e}")
            return None
    
    def reset(self):
        """Reset detector state"""
        self.last_check_time = 0
        self.frame_count = 0
        self.vehicle_detector.reset()
