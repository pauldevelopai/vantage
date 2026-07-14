"""
Camera Registry Store

JSONL-backed store for camera configurations.
Tracks all cameras (RTSP, ONVIF, Milestone, Genetec, mobile) with their
connection details and online/offline status.
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class Camera:
    """A registered camera"""
    camera_id: str          # Slug ID e.g. "entrance-north"
    name: str               # Human label e.g. "North Entrance"
    source: str             # RTSP URL, or "mobile" for phone cameras
    source_type: str        # "rtsp" | "onvif" | "milestone" | "genetec" | "mobile"
    enabled: bool = True
    location: str = ""      # Free text e.g. "Building A, Gate 1"
    area: str = ""          # Area/suburb name, links this camera to place-context (§9)
    status: str = "unknown"  # "online" | "offline" | "unknown"
    last_seen: Optional[str] = None  # ISO timestamp
    vms_config: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "source": self.source,
            "source_type": self.source_type,
            "enabled": self.enabled,
            "location": self.location,
            "area": self.area,
            "status": self.status,
            "last_seen": self.last_seen,
            "vms_config": self.vms_config or {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Camera":
        return cls(
            camera_id=data["camera_id"],
            name=data.get("name", data["camera_id"]),
            source=data.get("source", ""),
            source_type=data.get("source_type", "rtsp"),
            enabled=data.get("enabled", True),
            location=data.get("location", ""),
            area=data.get("area", ""),
            status=data.get("status", "unknown"),
            last_seen=data.get("last_seen"),
            vms_config=data.get("vms_config", {}),
        )


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


class CameraStore:
    """
    JSON-file-backed camera registry.

    Stores all cameras in a single JSON file (not JSONL) since the camera
    list is small and we need random access for updates/deletes.
    """

    def __init__(self, storage_path: str = "alibi/data/cameras_registry.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._cameras: Dict[str, Camera] = {}
        self._load()

    def _load(self):
        """Load cameras from disk."""
        if not self.storage_path.exists():
            self._cameras = {}
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
            self._cameras = {
                cam_data["camera_id"]: Camera.from_dict(cam_data)
                for cam_data in data.get("cameras", [])
            }
        except Exception as e:
            print(f"[CameraStore] Error loading: {e}")
            self._cameras = {}

    def _save(self):
        """Persist cameras to disk."""
        data = {
            "cameras": [cam.to_dict() for cam in self._cameras.values()]
        }
        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2)

    def add(self, camera: Camera) -> Camera:
        """Add a camera. Overwrites if camera_id already exists."""
        self._cameras[camera.camera_id] = camera
        self._save()
        return camera

    def get(self, camera_id: str) -> Optional[Camera]:
        """Get camera by ID."""
        return self._cameras.get(camera_id)

    def list_all(self) -> List[Camera]:
        """List all cameras."""
        return list(self._cameras.values())

    def update(self, camera_id: str, updates: Dict[str, Any]) -> Optional[Camera]:
        """Update camera fields. Returns updated camera or None if not found."""
        cam = self._cameras.get(camera_id)
        if cam is None:
            return None

        for key, value in updates.items():
            if hasattr(cam, key) and key != "camera_id":
                setattr(cam, key, value)

        self._save()
        return cam

    def remove(self, camera_id: str) -> bool:
        """Remove camera. Returns True if found and removed."""
        if camera_id in self._cameras:
            del self._cameras[camera_id]
            self._save()
            return True
        return False

    def update_status(self, camera_id: str, status: str, last_seen: Optional[str] = None):
        """Quick status update (called on every frame)."""
        cam = self._cameras.get(camera_id)
        if cam is None:
            return
        cam.status = status
        if last_seen:
            cam.last_seen = last_seen
        self._save()

    def upsert_mobile(self, camera_id: str, username: str) -> Camera:
        """Register or update a mobile camera."""
        existing = self._cameras.get(camera_id)
        now = datetime.now().isoformat()

        if existing:
            existing.status = "online"
            existing.last_seen = now
            self._save()
            return existing

        camera = Camera(
            camera_id=camera_id,
            name=f"Mobile - {username}",
            source="mobile",
            source_type="mobile",
            enabled=True,
            location="Mobile device",
            status="online",
            last_seen=now,
        )
        return self.add(camera)


# Global singleton
_store_instance: Optional[CameraStore] = None


def get_camera_store() -> CameraStore:
    """Get or create global camera store."""
    global _store_instance
    if _store_instance is None:
        _store_instance = CameraStore()
    return _store_instance
