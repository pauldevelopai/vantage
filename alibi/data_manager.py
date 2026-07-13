"""
Data Manager

Automatic data rotation, compression, and disk usage tracking.
Ensures Vantage stays within disk capacity limits with configurable
retention policies for snapshots, JSONL records, and face embeddings.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from alibi.encryption import get_encrypted_writer


DATA_DIR = Path("alibi/data")
SNAPSHOTS_DIR = DATA_DIR / "camera_snapshots"


@dataclass
class StorageBreakdown:
    """Disk usage summary."""
    total_bytes: int = 0
    snapshots_bytes: int = 0
    snapshots_count: int = 0
    thumbnails_bytes: int = 0
    thumbnails_count: int = 0
    jsonl_bytes: int = 0
    jsonl_files: int = 0
    config_bytes: int = 0
    other_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_mb": round(self.total_bytes / 1_048_576, 2),
            "snapshots_mb": round(self.snapshots_bytes / 1_048_576, 2),
            "snapshots_count": self.snapshots_count,
            "thumbnails_mb": round(self.thumbnails_bytes / 1_048_576, 2),
            "thumbnails_count": self.thumbnails_count,
            "jsonl_mb": round(self.jsonl_bytes / 1_048_576, 2),
            "jsonl_files": self.jsonl_files,
            "config_mb": round(self.config_bytes / 1_048_576, 2),
            "other_mb": round(self.other_bytes / 1_048_576, 2),
        }


class DataManager:
    """
    Manages disk usage with configurable retention policies.

    Rotation policies:
    - Snapshots: delete files older than max_days
    - JSONL: rewrite files keeping only recent records
    - Face sightings: drop embeddings from old records (keep metadata)
    """

    def __init__(
        self,
        data_dir: str = "alibi/data",
        snapshot_retention_days: int = 7,
        jsonl_retention_days: int = 14,
        face_embedding_retention_days: int = 30,
    ):
        self.data_dir = Path(data_dir)
        self.snapshots_dir = self.data_dir / "camera_snapshots"
        self.snapshot_retention_days = snapshot_retention_days
        self.jsonl_retention_days = jsonl_retention_days
        self.face_embedding_retention_days = face_embedding_retention_days
        self._crypto = get_encrypted_writer()

    def get_disk_usage(self) -> StorageBreakdown:
        """Calculate disk usage breakdown."""
        breakdown = StorageBreakdown()

        if not self.data_dir.exists():
            return breakdown

        for item in self.data_dir.rglob("*"):
            if not item.is_file():
                continue

            try:
                size = item.stat().st_size
            except OSError:
                continue

            breakdown.total_bytes += size

            # Categorize
            rel = item.relative_to(self.data_dir)
            parts = rel.parts

            if "camera_snapshots" in parts:
                if "thumbnails" in parts:
                    breakdown.thumbnails_bytes += size
                    breakdown.thumbnails_count += 1
                else:
                    breakdown.snapshots_bytes += size
                    breakdown.snapshots_count += 1
            elif item.suffix == ".jsonl":
                breakdown.jsonl_bytes += size
                breakdown.jsonl_files += 1
            elif item.suffix == ".json":
                breakdown.config_bytes += size
            else:
                breakdown.other_bytes += size

        return breakdown

    def rotate_snapshots(self, max_days: Optional[int] = None) -> Dict[str, int]:
        """
        Delete snapshots older than max_days.

        Returns:
            {"deleted_files": N, "freed_bytes": N}
        """
        max_days = max_days or self.snapshot_retention_days
        cutoff = datetime.now() - timedelta(days=max_days)
        deleted = 0
        freed = 0

        for subdir in [self.snapshots_dir, self.snapshots_dir / "thumbnails"]:
            if not subdir.exists():
                continue
            for f in subdir.glob("*.jpg"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        size = f.stat().st_size
                        f.unlink()
                        deleted += 1
                        freed += size
                except OSError:
                    continue

        if deleted:
            print(f"[DataManager] Rotated snapshots: deleted {deleted} files, freed {freed / 1_048_576:.1f} MB")

        return {"deleted_files": deleted, "freed_bytes": freed}

    def rotate_jsonl(self, file_path: Path, max_days: Optional[int] = None) -> Dict[str, int]:
        """
        Rewrite a JSONL file keeping only records within max_days.

        Expects records to have a 'timestamp' or 'ts' field.

        Returns:
            {"kept": N, "removed": N, "freed_bytes": N}
        """
        max_days = max_days or self.jsonl_retention_days

        if not file_path.exists():
            return {"kept": 0, "removed": 0, "freed_bytes": 0}

        cutoff = datetime.utcnow() - timedelta(days=max_days)
        original_size = file_path.stat().st_size

        kept_records = []
        removed = 0

        for data in self._crypto.read_lines(file_path):
            try:
                ts_str = data.get("timestamp") or data.get("ts") or data.get("created_at") or ""
                if ts_str:
                    record_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if record_time < cutoff:
                        removed += 1
                        continue
                kept_records.append(data)
            except (ValueError, AttributeError):
                kept_records.append(data)  # Keep records we can't parse

        # Rewrite file
        temp_path = file_path.with_suffix(".tmp")
        temp_path.touch()
        for record in kept_records:
            self._crypto.write_line(temp_path, record)
        temp_path.replace(file_path)

        new_size = file_path.stat().st_size
        freed = original_size - new_size

        if removed:
            print(f"[DataManager] Rotated {file_path.name}: kept {len(kept_records)}, removed {removed}, freed {freed / 1024:.1f} KB")

        return {"kept": len(kept_records), "removed": removed, "freed_bytes": max(0, freed)}

    def compact_face_sightings(self, max_days: Optional[int] = None) -> Dict[str, int]:
        """
        For face sightings older than max_days, drop the embedding
        (keep metadata only). Saves ~83% per old record.
        """
        max_days = max_days or self.face_embedding_retention_days
        sightings_path = self.data_dir / "face_sightings.jsonl"

        if not sightings_path.exists():
            return {"compacted": 0, "kept_full": 0}

        cutoff = datetime.utcnow() - timedelta(days=max_days)
        original_size = sightings_path.stat().st_size

        records = []
        compacted = 0
        kept_full = 0

        for data in self._crypto.read_lines(sightings_path):
            try:
                ts_str = data.get("ts", "")
                if ts_str:
                    record_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if record_time < cutoff and "embedding" in data:
                        # Drop embedding, keep metadata
                        data["embedding"] = []
                        data["embedding_compacted"] = True
                        compacted += 1
                    else:
                        kept_full += 1
                records.append(data)
            except (ValueError, AttributeError):
                records.append(data)

        # Rewrite
        temp_path = sightings_path.with_suffix(".tmp")
        temp_path.touch()
        for record in records:
            self._crypto.write_line(temp_path, record)
        temp_path.replace(sightings_path)

        new_size = sightings_path.stat().st_size
        freed = original_size - new_size

        if compacted:
            print(f"[DataManager] Compacted {compacted} face sightings, freed {freed / 1024:.1f} KB")

        return {"compacted": compacted, "kept_full": kept_full, "freed_bytes": max(0, freed)}

    def auto_rotate(self) -> Dict[str, Any]:
        """
        Run all rotation policies.

        Returns summary of what was cleaned up.
        """
        print("[DataManager] Running auto-rotation...")

        results = {}

        # 1. Rotate snapshots
        results["snapshots"] = self.rotate_snapshots()

        # 2. Rotate large JSONL files
        jsonl_files_to_rotate = [
            "camera_analysis.jsonl",
            "audit.jsonl",
            "events.jsonl",
            "cross_camera_sightings.jsonl",
            "anomaly_scores.jsonl",
        ]
        results["jsonl"] = {}
        for filename in jsonl_files_to_rotate:
            path = self.data_dir / filename
            if path.exists() and path.stat().st_size > 0:
                results["jsonl"][filename] = self.rotate_jsonl(path)

        # 3. Compact old face sightings
        results["face_sightings"] = self.compact_face_sightings()

        # Summary
        total_freed = results["snapshots"].get("freed_bytes", 0)
        for r in results["jsonl"].values():
            total_freed += r.get("freed_bytes", 0)
        total_freed += results["face_sightings"].get("freed_bytes", 0)

        results["total_freed_mb"] = round(total_freed / 1_048_576, 2)
        print(f"[DataManager] Auto-rotation complete. Freed {results['total_freed_mb']} MB")

        return results


# Global singleton
_manager: Optional[DataManager] = None


def get_data_manager() -> DataManager:
    """Get the global DataManager instance."""
    global _manager
    if _manager is None:
        _manager = DataManager()
    return _manager
