"""
Red Light Enforcement Detector Plugin

Integrates red light violation detection into the Vantage video worker pipeline.
"""

import numpy as np
from typing import Optional, Dict, Any
from pathlib import Path

from alibi.video.detectors.base import Detector, DetectionResult
from alibi.video.zones import Zone
from alibi.traffic.config import load_traffic_cameras, TrafficCameraConfig
from alibi.traffic.red_light_detector import RedLightViolationDetector


class RedLightEnforcementDetector(Detector):
    """
    Red light enforcement detector for Vantage video worker.
    
    Monitors traffic cameras for red light violations.
    ALWAYS requires human verification. NO automated citations.
    """
    
    def __init__(
        self,
        name: str = "red_light",
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize detector.
        
        Config options:
        - config_path: Path to traffic_cameras.json
        - evidence_dir: Directory for evidence files
        """
        super().__init__(name, config)
        
        # Configuration
        config_path = self.config.get('config_path', 'alibi/data/traffic_cameras.json')
        evidence_dir = self.config.get('evidence_dir', 'alibi/data/evidence')
        
        # Load traffic camera configurations
        self.camera_configs = load_traffic_cameras(config_path)
        
        # Create detector for each configured camera
        self.detectors: Dict[str, RedLightViolationDetector] = {}
        for camera_id, camera_config in self.camera_configs.items():
            if camera_config.enabled:
                self.detectors[camera_id] = RedLightViolationDetector(
                    camera_config=camera_config,
                    evidence_dir=evidence_dir
                )
        
        print(f"[RedLightEnforcement] Initialized {len(self.detectors)} traffic cameras")
    
    def detect(
        self,
        frame: np.ndarray,
        timestamp: float,
        camera_id: Optional[str] = None,
        zone: Optional[Zone] = None,
        **kwargs
    ) -> Optional[DetectionResult]:
        """
        Detect red light violations in frame.
        
        Args:
            frame: Input frame
            timestamp: Frame timestamp
            camera_id: Camera ID (required for traffic cameras)
            zone: Optional zone (not used for traffic detection)
            
        Returns:
            DetectionResult if violation detected, None otherwise
        """
        if not self.enabled:
            return None
        
        # Check if this camera is configured for traffic enforcement
        if camera_id not in self.detectors:
            return None
        
        # Get detector for this camera
        detector = self.detectors[camera_id]
        
        # Process frame
        violation_event = detector.process_frame(frame, timestamp)
        
        if violation_event:
            # Convert to DetectionResult
            return DetectionResult(
                detected=True,
                event_type=violation_event["event_type"],
                confidence=violation_event["confidence"],
                severity=violation_event["severity"],
                zone_id=None,  # Traffic cameras don't use zones
                metadata=violation_event["metadata"]
            )
        
        return None
    
    def reset(self):
        """Reset all detectors"""
        for detector in self.detectors.values():
            detector.reset()
    
    def get_camera_config(self, camera_id: str) -> Optional[TrafficCameraConfig]:
        """Get configuration for a specific camera"""
        return self.camera_configs.get(camera_id)
    
    def is_traffic_camera(self, camera_id: str) -> bool:
        """Check if camera is configured for traffic enforcement"""
        return camera_id in self.detectors
