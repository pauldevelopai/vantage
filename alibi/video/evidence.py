"""
Vantage Evidence Capture

Rolling buffer recorder for saving snapshots and video clips when events are detected.
"""

import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional
from collections import deque
from dataclasses import dataclass


@dataclass
class TimestampedFrame:
    """Frame with timestamp"""
    frame: np.ndarray
    timestamp: float  # Unix timestamp


class RollingBufferRecorder:
    """
    Maintains a rolling buffer of frames for evidence capture.
    
    When an event is detected, can extract:
    - Snapshot at specific timestamp
    - Video clip covering a time range
    """
    
    def __init__(
        self,
        camera_id: str,
        buffer_seconds: float = 10.0,
        fps: float = 1.0
    ):
        """
        Initialize recorder.
        
        Args:
            camera_id: Camera identifier
            buffer_seconds: How many seconds of history to keep
            fps: Expected frame rate (frames per second)
        """
        self.camera_id = camera_id
        self.buffer_seconds = buffer_seconds
        self.fps = fps
        
        # Calculate buffer size
        self.max_frames = int(buffer_seconds * fps)
        
        # Rolling buffer using deque for efficient append/pop
        self.buffer: deque[TimestampedFrame] = deque(maxlen=self.max_frames)
        
        # Track statistics
        self.frames_received = 0
        self.frames_dropped = 0
    
    def add_frame(self, frame: np.ndarray, timestamp: float):
        """
        Add frame to rolling buffer.
        
        Args:
            frame: Video frame (numpy array)
            timestamp: Unix timestamp when frame was captured
        """
        if frame is None or frame.size == 0:
            self.frames_dropped += 1
            return
        
        # Make a copy to avoid issues with frame reuse
        frame_copy = frame.copy()
        
        self.buffer.append(TimestampedFrame(frame=frame_copy, timestamp=timestamp))
        self.frames_received += 1
    
    def get_frame_at_time(self, target_timestamp: float) -> Optional[np.ndarray]:
        """
        Get frame closest to target timestamp.
        
        Args:
            target_timestamp: Target time
            
        Returns:
            Frame closest to target time, or None if buffer is empty
        """
        if not self.buffer:
            return None
        
        # Find frame with closest timestamp
        closest_frame = min(
            self.buffer,
            key=lambda tf: abs(tf.timestamp - target_timestamp)
        )
        
        return closest_frame.frame
    
    def get_frames_in_range(
        self,
        start_timestamp: float,
        end_timestamp: float
    ) -> List[TimestampedFrame]:
        """
        Get all frames within time range.
        
        Args:
            start_timestamp: Start of range
            end_timestamp: End of range
            
        Returns:
            List of frames in chronological order
        """
        frames = [
            tf for tf in self.buffer
            if start_timestamp <= tf.timestamp <= end_timestamp
        ]
        
        # Sort by timestamp to ensure chronological order
        frames.sort(key=lambda tf: tf.timestamp)
        
        return frames
    
    def get_stats(self) -> dict:
        """Get recorder statistics"""
        return {
            "camera_id": self.camera_id,
            "buffer_size": len(self.buffer),
            "max_frames": self.max_frames,
            "frames_received": self.frames_received,
            "frames_dropped": self.frames_dropped,
        }


def save_snapshot(
    frame: np.ndarray,
    out_dir: Path,
    camera_id: str,
    timestamp: float
) -> str:
    """
    Save snapshot image to disk.
    
    Args:
        frame: Video frame to save
        out_dir: Output directory
        camera_id: Camera identifier
        timestamp: Frame timestamp
        
    Returns:
        Relative file path (for URL generation)
    """
    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename: snapshot_<camera>_<timestamp>.jpg
    dt = datetime.fromtimestamp(timestamp)
    filename = f"snapshot_{camera_id}_{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
    filepath = out_dir / filename
    
    # Save as JPEG with good quality
    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    
    # Return relative path for URL
    return f"snapshots/{filename}"


def save_clip(
    frames: List[TimestampedFrame],
    out_dir: Path,
    camera_id: str,
    ts_start: float,
    ts_end: float,
    fps: float = 1.0
) -> str:
    """
    Save video clip to disk.
    
    Args:
        frames: List of timestamped frames
        out_dir: Output directory
        camera_id: Camera identifier
        ts_start: Start timestamp (for filename)
        ts_end: End timestamp (for filename)
        fps: Frame rate for output video
        
    Returns:
        Relative file path (for URL generation)
    """
    if not frames:
        raise ValueError("No frames to save")
    
    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename: clip_<camera>_<start>_<end>.mp4
    dt_start = datetime.fromtimestamp(ts_start)
    filename = f"clip_{camera_id}_{dt_start.strftime('%Y%m%d_%H%M%S')}.mp4"
    filepath = out_dir / filename
    
    # Get frame dimensions from first frame
    height, width = frames[0].frame.shape[:2]
    
    # Initialize video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(
        str(filepath),
        fourcc,
        fps,
        (width, height)
    )
    
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open video writer for {filepath}")
    
    # Write frames
    for tf in frames:
        writer.write(tf.frame)
    
    # Release writer
    writer.release()
    
    # Return relative path for URL
    return f"clips/{filename}"


def extract_evidence(
    recorder: RollingBufferRecorder,
    event_timestamp: float,
    evidence_dir: Path,
    clip_before_seconds: float = 5.0,
    clip_after_seconds: float = 5.0,
    fps: float = 1.0
) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract snapshot and clip from recorder buffer.
    
    Args:
        recorder: RollingBufferRecorder instance
        event_timestamp: When the event was detected
        evidence_dir: Base directory for evidence storage
        clip_before_seconds: Seconds before event to include in clip
        clip_after_seconds: Seconds after event to include in clip
        fps: Frame rate for output clip
        
    Returns:
        Tuple of (snapshot_path, clip_path) - relative paths for URLs
        Either can be None if extraction fails
    """
    camera_id = recorder.camera_id
    snapshot_path = None
    clip_path = None
    
    # 1. Extract snapshot
    try:
        snapshot_frame = recorder.get_frame_at_time(event_timestamp)
        if snapshot_frame is not None:
            snapshot_dir = evidence_dir / "snapshots"
            snapshot_path = save_snapshot(
                snapshot_frame,
                snapshot_dir,
                camera_id,
                event_timestamp
            )
    except Exception as e:
        print(f"[Evidence] Failed to save snapshot: {e}")
    
    # 2. Extract clip
    try:
        clip_start = event_timestamp - clip_before_seconds
        clip_end = event_timestamp + clip_after_seconds
        
        clip_frames = recorder.get_frames_in_range(clip_start, clip_end)
        
        if clip_frames:
            clip_dir = evidence_dir / "clips"
            clip_path = save_clip(
                clip_frames,
                clip_dir,
                camera_id,
                clip_start,
                clip_end,
                fps
            )
    except Exception as e:
        print(f"[Evidence] Failed to save clip: {e}")
    
    return snapshot_path, clip_path
