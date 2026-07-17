"""
Multi-Object Tracking for Vision-First Incidents

Tracks objects across frames to enable:
- Track-level incidents (not frame-level spam)
- Time-based rules (loitering, dwell time)
- Continuous incident updates (open → update → close)

Uses YOLO's built-in ByteTrack for robust, efficient tracking.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import numpy as np
from collections import deque


@dataclass
class TrackState:
    """
    State of a tracked object across frames.
    
    Enables time-based rules:
    - Loitering: dwell time in zone > threshold
    - Restricted zone entry: time in restricted zone
    - Object left unattended: stationary for N seconds
    """
    
    # Identity
    track_id: int
    class_id: int
    class_name: str
    
    # Temporal
    first_seen: datetime
    last_seen: datetime
    frame_count: int = 0
    
    # Spatial
    current_bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    current_centroid: Tuple[float, float] = (0.0, 0.0)
    centroid_history: List[Tuple[float, float]] = field(default_factory=list)
    
    # Confidence
    max_confidence: float = 0.0
    avg_confidence: float = 0.0
    _confidence_sum: float = 0.0
    
    # Zone presence
    zone_presence: Dict[str, float] = field(default_factory=dict)  # zone_id -> seconds
    current_zones: List[str] = field(default_factory=list)
    zone_entry_times: Dict[str, datetime] = field(default_factory=dict)  # zone_id -> entry_time
    
    # Motion
    is_stationary: bool = False
    stationary_since: Optional[datetime] = None
    displacement_history: deque = field(default_factory=lambda: deque(maxlen=30))  # Last 30 frames
    
    def update(
        self,
        bbox: Tuple[int, int, int, int],
        confidence: float,
        timestamp: datetime,
        zones: List[str]
    ):
        """
        Update track state with new detection.
        
        Args:
            bbox: Bounding box (x, y, w, h)
            confidence: Detection confidence
            timestamp: Current frame timestamp
            zones: List of zone IDs this detection is in
        """
        self.last_seen = timestamp
        self.frame_count += 1
        
        # Update bbox and centroid
        self.current_bbox = bbox
        x, y, w, h = bbox
        new_centroid = (x + w / 2, y + h / 2)
        
        # Calculate displacement (for motion/stationary detection)
        if self.current_centroid != (0.0, 0.0):
            dx = new_centroid[0] - self.current_centroid[0]
            dy = new_centroid[1] - self.current_centroid[1]
            displacement = np.sqrt(dx*dx + dy*dy)
            self.displacement_history.append(displacement)
            
            # Check if stationary (avg displacement < 5 pixels over last 30 frames)
            if len(self.displacement_history) >= 10:
                avg_displacement = np.mean(self.displacement_history)
                if avg_displacement < 5.0:
                    if not self.is_stationary:
                        self.is_stationary = True
                        self.stationary_since = timestamp
                else:
                    self.is_stationary = False
                    self.stationary_since = None
        
        self.current_centroid = new_centroid
        self.centroid_history.append(new_centroid)
        
        # Update confidence
        self.max_confidence = max(self.max_confidence, confidence)
        self._confidence_sum += confidence
        self.avg_confidence = self._confidence_sum / self.frame_count
        
        # Update zone presence
        time_delta = (timestamp - self.last_seen).total_seconds() if self.frame_count > 1 else 0.0
        
        # Update existing zones
        for zone_id in zones:
            if zone_id not in self.zone_presence:
                self.zone_presence[zone_id] = 0.0
                self.zone_entry_times[zone_id] = timestamp
            self.zone_presence[zone_id] += time_delta
        
        self.current_zones = zones
    
    @property
    def duration_seconds(self) -> float:
        """Total time this track has been observed"""
        return (self.last_seen - self.first_seen).total_seconds()
    
    @property
    def stationary_duration_seconds(self) -> float:
        """How long this track has been stationary"""
        if self.stationary_since:
            return (self.last_seen - self.stationary_since).total_seconds()
        return 0.0
    
    def dwell_time_in_zone(self, zone_id: str) -> float:
        """How long this track has been in a specific zone (seconds)"""
        return self.zone_presence.get(zone_id, 0.0)
    
    def is_in_zone(self, zone_id: str) -> bool:
        """Is this track currently in the given zone?"""
        return zone_id in self.current_zones
    
    def to_dict(self) -> Dict:
        """Convert to dict for storage/serialization"""
        return {
            "track_id": self.track_id,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "current_bbox": self.current_bbox,
            "current_centroid": self.current_centroid,
            "max_confidence": self.max_confidence,
            "avg_confidence": self.avg_confidence,
            "zone_presence": self.zone_presence,
            "current_zones": self.current_zones,
            "is_stationary": self.is_stationary,
            "stationary_duration": self.stationary_duration_seconds,
            "path_length": len(self.centroid_history)
        }


def _is_detection_list(x) -> bool:
    """True for a list of backend-agnostic Detection objects (as opposed to
    ultralytics YOLO results)."""
    from alibi.vision.simple_tracker import Detection
    return isinstance(x, list) and (not x or isinstance(x[0], Detection))


class MultiObjectTracker:
    """
    Manages tracking of multiple objects across frames.
    
    Uses YOLO's built-in ByteTrack for robust tracking:
    - Handles occlusions
    - Re-identifies tracks after temporary disappearance
    - Efficient (minimal overhead)
    
    Maintains TrackState for each track to enable time-based rules.
    """
    
    def __init__(
        self,
        max_age: int = 30,  # Frames to keep track without detection
        min_hits: int = 3    # Min detections before track is confirmed
    ):
        """
        Initialize tracker.
        
        Args:
            max_age: Frames before track is considered lost
            min_hits: Minimum detections before track is confirmed
        """
        self.max_age = max_age
        self.min_hits = min_hits
        
        # Active tracks: track_id -> TrackState
        self.tracks: Dict[int, TrackState] = {}
        
        # Assigns track IDs when we're given raw detections — this is what
        # replaced ultralytics' internal ByteTrack (AGPL).
        from alibi.vision.simple_tracker import SimpleTracker
        self._assoc = SimpleTracker()

        # Tracks pending confirmation (need min_hits)
        self.pending_tracks: Dict[int, TrackState] = {}
        
        # Lost tracks (for potential re-identification)
        self.lost_tracks: Dict[int, TrackState] = {}
        
        # Frame counter
        self.frame_count = 0
    
    def update(
        self,
        yolo_results,
        zones_config: Optional[List[Dict]] = None,
        timestamp: Optional[datetime] = None
    ) -> Dict[int, TrackState]:
        """
        Update tracker with new YOLO results.
        
        YOLO results must have tracking enabled:
        model.track(frame, persist=True)
        
        Args:
            yolo_results: YOLO results with tracking
            zones_config: Optional zones configuration for zone presence
            timestamp: Optional timestamp (defaults to now)
            
        Returns:
            Dict of active tracks: track_id -> TrackState
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        self.frame_count += 1

        # Two ways in, one set of bookkeeping below.
        #
        # Preferred: a list of Detection (from any detector — D-FINE, Apache-2.0).
        # We assign the track IDs ourselves via SimpleTracker, so no AGPL code is
        # involved and detection isn't run twice.
        #
        # Legacy: ultralytics YOLO results, which arrive with IDs already attached
        # because YOLO ran ByteTrack internally. Kept so existing callers and the
        # simulator keep working, but nothing on a live path uses it.
        detections = []
        if _is_detection_list(yolo_results):
            for tr in self._assoc.update(list(yolo_results), timestamp).values():
                x, y, w, h = tr.bbox
                zones = tr.zones
                if zones_config and not zones:
                    zones = self._get_zones_for_point((x + w / 2, y + h / 2), zones_config)
                detections.append({
                    "track_id": tr.track_id,
                    "class_id": tr.class_id,
                    "class_name": tr.class_name,
                    "bbox": tr.bbox,
                    "confidence": tr.confidence,
                    "zones": zones,
                })
            return self._apply_detections(detections, timestamp)

        for result in yolo_results:
            if hasattr(result.boxes, 'id') and result.boxes.id is not None:
                boxes = result.boxes
                for i, track_id in enumerate(boxes.id):
                    track_id = int(track_id)
                    box = boxes.xyxy[i].cpu().numpy()
                    conf = float(boxes.conf[i])
                    cls = int(boxes.cls[i])
                    class_name = result.names[cls]
                    
                    # Convert to x, y, w, h
                    x1, y1, x2, y2 = box
                    x, y = int(x1), int(y1)
                    w, h = int(x2 - x1), int(y2 - y1)
                    bbox = (x, y, w, h)
                    
                    # Determine zones
                    cx, cy = x + w / 2, y + h / 2
                    zones = []
                    if zones_config:
                        zones = self._get_zones_for_point((cx, cy), zones_config)
                    
                    detections.append({
                        "track_id": track_id,
                        "class_id": cls,
                        "class_name": class_name,
                        "bbox": bbox,
                        "confidence": conf,
                        "zones": zones
                    })
        
        return self._apply_detections(detections, timestamp)

    def _apply_detections(self, detections, timestamp):
        """TrackState bookkeeping, shared by both input paths: pending vs
        confirmed, min_hits, dwell, and retiring what is no longer seen."""
        # Update existing tracks or create new ones
        updated_track_ids = set()
        for det in detections:
            track_id = det["track_id"]
            updated_track_ids.add(track_id)
            
            # Check if track exists
            if track_id in self.tracks:
                # Update existing confirmed track
                self.tracks[track_id].update(
                    det["bbox"],
                    det["confidence"],
                    timestamp,
                    det["zones"]
                )
            elif track_id in self.pending_tracks:
                # Update pending track
                self.pending_tracks[track_id].update(
                    det["bbox"],
                    det["confidence"],
                    timestamp,
                    det["zones"]
                )
                
                # Confirm track if min_hits reached
                if self.pending_tracks[track_id].frame_count >= self.min_hits:
                    self.tracks[track_id] = self.pending_tracks.pop(track_id)
            else:
                # New track
                track = TrackState(
                    track_id=track_id,
                    class_id=det["class_id"],
                    class_name=det["class_name"],
                    first_seen=timestamp,
                    last_seen=timestamp,
                    current_bbox=det["bbox"],
                    current_centroid=(
                        det["bbox"][0] + det["bbox"][2] / 2,
                        det["bbox"][1] + det["bbox"][3] / 2
                    ),
                    max_confidence=det["confidence"],
                    avg_confidence=det["confidence"],
                    _confidence_sum=det["confidence"],
                    frame_count=1,
                    current_zones=det["zones"]
                )
                
                # Initialize zone entry times
                for zone_id in det["zones"]:
                    track.zone_entry_times[zone_id] = timestamp
                
                # Add to pending tracks
                self.pending_tracks[track_id] = track
        
        # Remove stale tracks (not seen for max_age frames)
        # For now, we'll just keep all tracks (no auto-removal)
        # In production, you'd remove tracks not seen for max_age frames
        
        return self.tracks

    
    def _get_zones_for_point(
        self,
        point: Tuple[float, float],
        zones_config: List[Dict]
    ) -> List[str]:
        """
        Check which zones a point is inside.
        
        Args:
            point: (x, y) centroid
            zones_config: List of zone dicts with polygon and id
            
        Returns:
            List of zone IDs
        """
        import cv2
        
        zones = []
        px, py = int(point[0]), int(point[1])
        
        for zone in zones_config:
            polygon = zone.get("polygon", [])
            if not polygon:
                continue
            
            poly_array = np.array(polygon, dtype=np.int32)
            if cv2.pointPolygonTest(poly_array, (px, py), False) >= 0:
                zones.append(zone["id"])
        
        return zones
    
    def get_track(self, track_id: int) -> Optional[TrackState]:
        """Get a specific track by ID"""
        return self.tracks.get(track_id)
    
    def get_active_tracks(self) -> Dict[int, TrackState]:
        """Get all confirmed active tracks"""
        return self.tracks.copy()
    
    def get_tracks_in_zone(self, zone_id: str) -> List[TrackState]:
        """Get all tracks currently in a specific zone"""
        return [
            track for track in self.tracks.values()
            if track.is_in_zone(zone_id)
        ]
    
    def reset(self):
        """Reset tracker (clear all tracks)"""
        self.tracks.clear()
        self.pending_tracks.clear()
        self.lost_tracks.clear()
        self.frame_count = 0


def create_tracker_from_yolo(model, persist: bool = True) -> MultiObjectTracker:
    """
    Create a tracker configured for YOLO tracking.
    
    Args:
        model: YOLO model instance
        persist: Whether to persist tracks across calls
        
    Returns:
        Configured MultiObjectTracker
    """
    tracker = MultiObjectTracker(
        max_age=30,    # 1 second at 30 fps
        min_hits=3     # Confirm after 3 detections
    )
    return tracker
