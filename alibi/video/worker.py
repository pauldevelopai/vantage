"""
Vantage Video Worker

Main worker loop that processes video streams and posts events to API.
"""

import json
import time
import argparse
import requests
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass
import hashlib

from alibi.video.rtsp_reader import RTSPReader
from alibi.video.frame_sampler import FrameSampler, SamplerConfig
from alibi.video.zones import ZoneManager
from alibi.video.detectors.base import Detector, DetectionResult
from alibi.video.detectors.motion_detector import MotionDetector
from alibi.video.detectors.presence_after_hours import PresenceAfterHoursDetector
from alibi.video.detectors.loitering_detector import LoiteringDetector
from alibi.video.detectors.aggression_detector import AggressionDetector
from alibi.video.detectors.crowd_panic_detector import CrowdPanicDetector
from alibi.video.detectors.watchlist_detector import WatchlistDetector
from alibi.video.detectors.red_light_enforcement_detector import RedLightEnforcementDetector
from alibi.video.detectors.hotlist_plate_detector import HotlistPlateDetector
from alibi.video.detectors.vehicle_sighting_detector import VehicleSightingDetector
from alibi.video.detectors.plate_vehicle_mismatch_detector import PlateVehicleMismatchDetector
from alibi.video.evidence import RollingBufferRecorder, extract_evidence


@dataclass
class CameraConfig:
    """Camera configuration"""
    camera_id: str
    input: str  # RTSP URL or local file path
    zone_id: str
    enabled: bool = True
    sample_fps: float = 1.0


@dataclass
class WorkerConfig:
    """Worker configuration"""
    api_url: str
    cameras: List[CameraConfig]
    zones_config: str
    event_throttle_seconds: int = 30
    api_timeout: int = 10
    api_retry_max: int = 3
    api_retry_delay: float = 2.0
    evidence_dir: str = "alibi/data/evidence"
    evidence_buffer_seconds: float = 10.0
    evidence_clip_before: float = 5.0
    evidence_clip_after: float = 5.0


class EventThrottler:
    """
    Throttles duplicate events to prevent spam.
    
    Same camera+zone+event_type limited to once per X seconds,
    unless severity increases.
    """
    
    def __init__(self, throttle_seconds: int = 30):
        self.throttle_seconds = throttle_seconds
        self.last_events: Dict[str, Dict[str, Any]] = {}
    
    def should_send(
        self,
        camera_id: str,
        zone_id: str,
        event_type: str,
        severity: int,
        current_time: float
    ) -> bool:
        """
        Check if event should be sent.
        
        Args:
            camera_id: Camera ID
            zone_id: Zone ID
            event_type: Event type
            severity: Event severity
            current_time: Current timestamp
        
        Returns:
            True if should send event
        """
        key = f"{camera_id}:{zone_id}:{event_type}"
        
        if key not in self.last_events:
            self.last_events[key] = {
                'timestamp': current_time,
                'severity': severity,
            }
            return True
        
        last_event = self.last_events[key]
        time_elapsed = current_time - last_event['timestamp']
        
        # Send if enough time has passed
        if time_elapsed >= self.throttle_seconds:
            self.last_events[key] = {
                'timestamp': current_time,
                'severity': severity,
            }
            return True
        
        # Send if severity increased
        if severity > last_event['severity']:
            self.last_events[key] = {
                'timestamp': current_time,
                'severity': severity,
            }
            return True
        
        return False
    
    def cleanup_old_entries(self, current_time: float, max_age: float = 3600):
        """Remove old entries to prevent memory growth"""
        keys_to_remove = []
        
        for key, data in self.last_events.items():
            if current_time - data['timestamp'] > max_age:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.last_events[key]


class VideoWorker:
    """
    Main video processing worker.
    
    Reads cameras, processes frames, runs detectors, posts events to API.
    """
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        
        # Load zones
        self.zone_manager = ZoneManager(config.zones_config)
        
        # Create detectors - Digital Shield Suite + Watchlist + Traffic + Hotlist + Vehicle Sightings + Mismatch
        self.detectors: List[Detector] = [
            MotionDetector(name="motion"),
            PresenceAfterHoursDetector(name="after_hours"),
            LoiteringDetector(name="loitering"),
            AggressionDetector(name="aggression"),
            CrowdPanicDetector(name="crowd_panic"),
            WatchlistDetector(name="watchlist"),
            RedLightEnforcementDetector(name="red_light"),
            HotlistPlateDetector(name="hotlist_plate"),
            VehicleSightingDetector(name="vehicle_sighting"),
            PlateVehicleMismatchDetector(name="plate_vehicle_mismatch"),
        ]
        
        # Event throttler
        self.throttler = EventThrottler(config.event_throttle_seconds)
        
        # Statistics
        self.stats = {
            'frames_processed': 0,
            'events_detected': 0,
            'events_sent': 0,
            'events_throttled': 0,
            'api_errors': 0,
        }
    
    def process_camera(self, camera: CameraConfig):
        """
        Process single camera stream.
        
        Args:
            camera: Camera configuration
        """
        print(f"\n[Worker] Starting camera: {camera.camera_id}")
        print(f"[Worker]   Input: {camera.input}")
        print(f"[Worker]   Zone: {camera.zone_id}")
        print(f"[Worker]   Sample FPS: {camera.sample_fps}")
        
        # Get zone
        zone = self.zone_manager.get_zone(camera.zone_id)
        if not zone:
            print(f"[Worker] Warning: Zone {camera.zone_id} not found")
        
        # Create reader and sampler
        reader = RTSPReader(camera.input)
        sampler_config = SamplerConfig(target_fps=camera.sample_fps)
        sampler = FrameSampler(sampler_config)
        
        # Create evidence recorder for this camera
        recorder = RollingBufferRecorder(
            camera_id=camera.camera_id,
            buffer_seconds=self.config.evidence_buffer_seconds,
            fps=camera.sample_fps
        )
        print(f"[Worker]   Evidence buffer: {self.config.evidence_buffer_seconds}s")
        
        # Process frames
        try:
            for frame in sampler.sample(reader.frames()):
                self.stats['frames_processed'] += 1
                current_time = time.time()
                
                # Add frame to evidence buffer
                recorder.add_frame(frame, current_time)
                
                # Run detectors
                for detector in self.detectors:
                    if not detector.enabled:
                        continue
                    
                    result = detector.detect(frame, current_time, zone=zone)
                    
                    if result and result.detected:
                        self.stats['events_detected'] += 1
                        
                        # Check throttling
                        if not self.throttler.should_send(
                            camera.camera_id,
                            camera.zone_id,
                            result.event_type,
                            result.severity,
                            current_time
                        ):
                            self.stats['events_throttled'] += 1
                            continue
                        
                        # Send to API with evidence
                        success = self.send_event(camera, result, current_time, recorder)
                        
                        if success:
                            self.stats['events_sent'] += 1
                        else:
                            self.stats['api_errors'] += 1
                
                # Periodic status
                if self.stats['frames_processed'] % 100 == 0:
                    self.print_stats()
                
                # Periodic throttler cleanup
                if self.stats['frames_processed'] % 1000 == 0:
                    self.throttler.cleanup_old_entries(current_time)
        
        except Exception as e:
            print(f"[Worker] Error processing camera {camera.camera_id}: {e}")
        
        finally:
            print(f"\n[Worker] Stopped camera: {camera.camera_id}")
            self.print_stats()
    
    def send_event(
        self,
        camera: CameraConfig,
        result: DetectionResult,
        timestamp: float,
        recorder: RollingBufferRecorder
    ) -> bool:
        """
        Send event to API with retry logic.
        
        Args:
            camera: Camera configuration
            result: Detection result
            timestamp: Event timestamp
            recorder: Evidence recorder for extracting snapshot/clip
        
        Returns:
            True if successful
        """
        # Generate event ID
        event_id = self._generate_event_id(camera.camera_id, timestamp)
        
        # Extract evidence (snapshot + clip)
        evidence_dir = Path(self.config.evidence_dir)
        snapshot_path, clip_path = extract_evidence(
            recorder=recorder,
            event_timestamp=timestamp,
            evidence_dir=evidence_dir,
            clip_before_seconds=self.config.evidence_clip_before,
            clip_after_seconds=self.config.evidence_clip_after,
            fps=camera.sample_fps
        )
        
        # Build URLs (or None if extraction failed)
        snapshot_url = f"/evidence/{snapshot_path}" if snapshot_path else None
        clip_url = f"/evidence/{clip_path}" if clip_path else None
        
        # Build CameraEvent payload
        payload = {
            "event_id": event_id,
            "camera_id": camera.camera_id,
            "ts": datetime.fromtimestamp(timestamp).isoformat(),
            "zone_id": result.zone_id or camera.zone_id,
            "event_type": result.event_type,
            "confidence": result.confidence,
            "severity": result.severity,
            "clip_url": clip_url,
            "snapshot_url": snapshot_url,
            "metadata": result.metadata,
        }
        
        # Retry loop
        for attempt in range(self.config.api_retry_max):
            try:
                response = requests.post(
                    f"{self.config.api_url}/webhook/camera-event",
                    json=payload,
                    timeout=self.config.api_timeout
                )
                
                if response.status_code == 200:
                    incident_data = response.json()
                    print(f"[Worker] ✓ Event sent: {result.event_type} → {incident_data.get('incident_id')}")
                    return True
                else:
                    print(f"[Worker] API error {response.status_code}: {response.text}")
                    
            except requests.exceptions.Timeout:
                print(f"[Worker] API timeout (attempt {attempt+1}/{self.config.api_retry_max})")
            except requests.exceptions.ConnectionError:
                print(f"[Worker] API connection error (attempt {attempt+1}/{self.config.api_retry_max})")
            except Exception as e:
                print(f"[Worker] API error: {e}")
            
            # Exponential backoff
            if attempt < self.config.api_retry_max - 1:
                delay = self.config.api_retry_delay * (2 ** attempt)
                time.sleep(delay)
        
        print(f"[Worker] ✗ Failed to send event after {self.config.api_retry_max} attempts")
        return False
    
    def _generate_event_id(self, camera_id: str, timestamp: float) -> str:
        """Generate unique event ID"""
        base = f"{camera_id}_{timestamp}_{self.stats['events_sent']}"
        hash_suffix = hashlib.md5(base.encode()).hexdigest()[:8]
        return f"vid_{hash_suffix}"
    
    def print_stats(self):
        """Print worker statistics"""
        print(f"\n[Worker Stats]")
        print(f"  Frames processed: {self.stats['frames_processed']}")
        print(f"  Events detected: {self.stats['events_detected']}")
        print(f"  Events sent: {self.stats['events_sent']}")
        print(f"  Events throttled: {self.stats['events_throttled']}")
        print(f"  API errors: {self.stats['api_errors']}")
    
    def run(self):
        """
        Run worker for all cameras.
        
        For now, processes cameras sequentially.
        TODO: Multi-threaded or multi-process for parallel processing.
        """
        print("\n" + "="*60)
        print("Vantage Video Worker Starting")
        print("="*60)
        print(f"API URL: {self.config.api_url}")
        print(f"Cameras: {len(self.config.cameras)}")
        print(f"Zones: {len(self.zone_manager.zones)}")
        print(f"Detectors: {len(self.detectors)}")
        print(f"Throttle: {self.config.event_throttle_seconds}s")
        print("="*60)
        
        for camera in self.config.cameras:
            if not camera.enabled:
                print(f"\n[Worker] Skipping disabled camera: {camera.camera_id}")
                continue
            
            self.process_camera(camera)


def load_config(config_path: str, api_url: str, zones_config: str) -> WorkerConfig:
    """
    Load worker configuration from file.
    
    Args:
        config_path: Path to cameras.json
        api_url: API base URL
        zones_config: Path to zones.json
    
    Returns:
        WorkerConfig
    """
    with open(config_path, 'r') as f:
        config_data = json.load(f)
    
    cameras = []
    for cam_data in config_data.get('cameras', []):
        cameras.append(CameraConfig(
            camera_id=cam_data['camera_id'],
            input=cam_data['input'],
            zone_id=cam_data['zone_id'],
            enabled=cam_data.get('enabled', True),
            sample_fps=cam_data.get('sample_fps', 1.0),
        ))
    
    return WorkerConfig(
        api_url=api_url,
        cameras=cameras,
        zones_config=zones_config,
        event_throttle_seconds=config_data.get('event_throttle_seconds', 30),
        api_timeout=config_data.get('api_timeout', 10),
        api_retry_max=config_data.get('api_retry_max', 3),
        api_retry_delay=config_data.get('api_retry_delay', 2.0),
    )


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='Vantage Video Worker')
    parser.add_argument(
        '--config',
        required=True,
        help='Path to cameras.json configuration file'
    )
    parser.add_argument(
        '--api',
        default=os.getenv('ALIBI_API_URL', 'http://localhost:8000'),
        help='API base URL (default: $ALIBI_API_URL or http://localhost:8000)'
    )
    parser.add_argument(
        '--zones',
        default='alibi/data/zones.json',
        help='Path to zones.json (default: alibi/data/zones.json)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config(args.config, args.api, args.zones)
    except FileNotFoundError as e:
        print(f"Error: Configuration file not found: {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration: {e}")
        return 1
    
    # Create and run worker
    worker = VideoWorker(config)
    
    try:
        worker.run()
    except KeyboardInterrupt:
        print("\n\n[Worker] Interrupted by user")
        worker.print_stats()
    except Exception as e:
        print(f"\n\n[Worker] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
