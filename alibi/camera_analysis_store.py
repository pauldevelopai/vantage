"""
Camera Analysis Store - Persistent storage for camera feed analysis

Stores all camera analysis results for:
- Historical review
- Pattern analysis
- Incident correlation
- Training data
- Audit trail
"""

import json
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import os
import hashlib

from alibi.encryption import get_encrypted_writer


@dataclass
class CameraAnalysis:
    """Single camera analysis record"""
    analysis_id: str
    timestamp: str
    user: str
    camera_source: str  # "webcam", "mobile", "rtsp_camera_1", etc.
    description: str
    confidence: float
    detected_objects: List[str]
    detected_activities: List[str]
    safety_concern: bool
    method: str  # "openai_vision", "google_vision", "basic_cv"
    metadata: Dict[str, Any]
    snapshot_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    

class CameraAnalysisStore:
    """
    Manages persistent storage of camera analysis results.
    
    Storage format: JSONL (one JSON object per line)
    File: alibi/data/camera_analysis.jsonl
    
    Features:
    - Append-only for audit trail
    - Fast queries by date range
    - Pattern detection
    - Export for reporting
    """
    
    def __init__(self, store_file: str = "alibi/data/camera_analysis.jsonl",
                 snapshots_dir: str = "alibi/data/camera_snapshots",
                 retention_days: int = 7):
        self.store_file = Path(store_file)
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()

        # Snapshot storage
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        (self.snapshots_dir / "thumbnails").mkdir(exist_ok=True)

        # Retention policy
        self.retention_days = retention_days

        # Create file if it doesn't exist
        if not self.store_file.exists():
            self.store_file.touch()
    
    def save_snapshot(self, frame: np.ndarray, analysis_id: str) -> tuple[str, str]:
        """
        Save a snapshot and thumbnail from camera frame.
        
        Returns: (snapshot_path, thumbnail_path)
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{analysis_id}.jpg"
        
        # Cap resolution to 1280px wide to save disk space
        height, width = frame.shape[:2]
        if width > 1280:
            scale = 1280 / width
            frame = cv2.resize(frame, (1280, int(height * scale)))
            height, width = frame.shape[:2]

        # Save full snapshot (quality 70 — good visual fidelity, ~40% smaller than 85)
        snapshot_path = self.snapshots_dir / filename
        cv2.imwrite(str(snapshot_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 70])

        # Create thumbnail (max 320px width, quality 50)
        if width > 320:
            scale = 320 / width
            new_width = 320
            new_height = int(height * scale)
            thumbnail = cv2.resize(frame, (new_width, new_height))
        else:
            thumbnail = frame

        thumbnail_path = self.snapshots_dir / "thumbnails" / filename
        cv2.imwrite(str(thumbnail_path), thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 50])
        
        return (f"/camera_snapshots/{filename}", f"/camera_snapshots/thumbnails/{filename}")
    
    def cleanup_old_snapshots(self) -> int:
        """
        Delete snapshots older than retention_days.
        
        Returns: Number of files deleted
        """
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        deleted = 0
        
        # Clean up full snapshots
        for file in self.snapshots_dir.glob("*.jpg"):
            file_time = datetime.fromtimestamp(file.stat().st_mtime)
            if file_time < cutoff:
                file.unlink()
                deleted += 1
        
        # Clean up thumbnails
        thumbnail_dir = self.snapshots_dir / "thumbnails"
        for file in thumbnail_dir.glob("*.jpg"):
            file_time = datetime.fromtimestamp(file.stat().st_mtime)
            if file_time < cutoff:
                file.unlink()
                deleted += 1
        
        # Also clean up old records from JSONL
        self._cleanup_old_records()
        
        return deleted
    
    def _cleanup_old_records(self):
        """Remove records older than retention_days from JSONL file"""
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        temp_file = self.store_file.with_suffix('.tmp')
        kept = 0
        
        with open(self.store_file, 'r') as f_in, open(temp_file, 'w') as f_out:
            for line in f_in:
                if line.strip():
                    data = json.loads(line)
                    record_time = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                    if record_time >= cutoff:
                        f_out.write(line)
                        kept += 1
        
        # Replace original with temp
        temp_file.replace(self.store_file)
        
        return kept
    
    def add_analysis(self, analysis: CameraAnalysis) -> None:
        """Add a camera analysis record (encrypted at rest)"""
        self._crypto.write_line(self.store_file, asdict(analysis))
        
        # Automatically collect for training if security-relevant
        try:
            from alibi.training_agent import get_training_agent
            agent = get_training_agent()
            
            # Convert to dict for agent processing
            analysis_dict = {
                "timestamp": analysis.timestamp,
                "description": analysis.description,
                "objects": analysis.detected_objects,
                "activities": analysis.detected_activities,
                "safety_concerns": [] if not analysis.safety_concern else ["Safety concern flagged"],
                "confidence": analysis.confidence,
                "image_hash": hashlib.md5(f"{analysis.timestamp}_{analysis.description}".encode()).hexdigest()
            }
            
            # Check if should collect
            should_collect, category, reason = agent.should_collect(analysis_dict)
            
            if should_collect:
                example = agent.collect_example(analysis_dict, category, reason)
                agent.save_example(example)
        except Exception as e:
            # Don't fail if agent collection fails
            pass
    
    def get_recent(self, limit: int = 100, hours: int = 24) -> List[CameraAnalysis]:
        """Get recent analysis records"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        results = []

        for data in self._crypto.read_lines(self.store_file):
            try:
                record_time = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                if record_time >= cutoff:
                    results.append(CameraAnalysis(**data))
            except (KeyError, ValueError):
                continue

        # Return most recent first
        results.sort(key=lambda x: x.timestamp, reverse=True)
        return results[:limit]
    
    def get_by_date_range(self, start: datetime, end: datetime) -> List[CameraAnalysis]:
        """Get analysis records in a date range"""
        results = []

        for data in self._crypto.read_lines(self.store_file):
            try:
                record_time = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                if start <= record_time <= end:
                    results.append(CameraAnalysis(**data))
            except (KeyError, ValueError):
                continue

        return results
    
    def get_safety_concerns(self, hours: int = 24) -> List[CameraAnalysis]:
        """Get all safety concerns detected"""
        recent = self.get_recent(limit=1000, hours=hours)
        return [r for r in recent if r.safety_concern]
    
    def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Get analysis statistics"""
        recent = self.get_recent(limit=10000, hours=hours)
        
        if not recent:
            return {
                "total_analyses": 0,
                "safety_concerns": 0,
                "most_common_objects": [],
                "most_common_activities": [],
                "analysis_methods": {},
                "time_range": f"last_{hours}_hours"
            }
        
        # Count objects
        object_counts = {}
        for record in recent:
            for obj in record.detected_objects:
                object_counts[obj] = object_counts.get(obj, 0) + 1
        
        # Count activities
        activity_counts = {}
        for record in recent:
            for activity in record.detected_activities:
                activity_counts[activity] = activity_counts.get(activity, 0) + 1
        
        # Count methods
        method_counts = {}
        for record in recent:
            method_counts[record.method] = method_counts.get(record.method, 0) + 1
        
        # Sort and get top items
        top_objects = sorted(object_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_activities = sorted(activity_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "total_analyses": len(recent),
            "safety_concerns": len([r for r in recent if r.safety_concern]),
            "most_common_objects": [{"object": obj, "count": count} for obj, count in top_objects],
            "most_common_activities": [{"activity": act, "count": count} for act, count in top_activities],
            "analysis_methods": method_counts,
            "time_range": f"last_{hours}_hours",
            "unique_users": len(set(r.user for r in recent)),
            "unique_cameras": len(set(r.camera_source for r in recent))
        }
    
    def export_for_report(self, start: datetime, end: datetime) -> str:
        """Export analysis data as markdown for reports"""
        records = self.get_by_date_range(start, end)
        
        if not records:
            return "No camera analysis data for this period."
        
        md = f"# Camera Analysis Report\n\n"
        md += f"**Period:** {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')}\n\n"
        md += f"**Total Analyses:** {len(records)}\n\n"
        
        # Safety concerns
        concerns = [r for r in records if r.safety_concern]
        if concerns:
            md += f"## ⚠️ Safety Concerns ({len(concerns)})\n\n"
            for concern in concerns[:20]:  # Top 20
                md += f"- **{concern.timestamp}**: {concern.description}\n"
            md += "\n"
        
        # Statistics
        stats = self.get_statistics(hours=(end - start).total_seconds() / 3600)
        md += f"## 📊 Statistics\n\n"
        md += f"- **Total Analyses:** {stats['total_analyses']}\n"
        md += f"- **Safety Concerns:** {stats['safety_concerns']}\n"
        md += f"- **Unique Users:** {stats['unique_users']}\n"
        md += f"- **Unique Cameras:** {stats['unique_cameras']}\n\n"
        
        if stats['most_common_objects']:
            md += "### Most Detected Objects\n\n"
            for item in stats['most_common_objects'][:5]:
                md += f"- {item['object']}: {item['count']}\n"
            md += "\n"
        
        if stats['most_common_activities']:
            md += "### Most Common Activities\n\n"
            for item in stats['most_common_activities'][:5]:
                md += f"- {item['activity']}: {item['count']}\n"
            md += "\n"
        
        return md


# Global store instance
_store = None

def get_camera_analysis_store() -> CameraAnalysisStore:
    """Get global camera analysis store instance"""
    global _store
    if _store is None:
        _store = CameraAnalysisStore()
    return _store
