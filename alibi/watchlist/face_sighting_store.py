"""
Face Sighting Store

JSONL storage for every detected face — not just watchlist matches.
Enables "Have we seen this person before?" queries and cross-camera
face tracking for all detected individuals.

Modeled on alibi/vehicles/sightings_store.py.
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict

from alibi.encryption import get_encrypted_writer


@dataclass
class FaceSighting:
    """A recorded face sighting from camera analysis."""
    sighting_id: str
    camera_id: str
    ts: str                                # ISO timestamp
    embedding: List[float]                 # 128-d L2-normalized
    bbox: Tuple[int, int, int, int]        # (x, y, w, h)
    confidence: float
    matched_person_id: Optional[str] = None   # Watchlist person_id if matched
    match_score: Optional[float] = None       # Cosine similarity if matched
    image_path: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage.
        Embeddings stored as base64-encoded float16 for 83% size reduction.
        """
        import base64

        # Compress embedding: 128 floats as float16 → 256 bytes → ~344 chars base64
        # vs ~2000 chars as JSON float list
        emb = self.embedding
        if emb and len(emb) > 0:
            arr = np.array(emb, dtype=np.float16)
            emb_compressed = base64.b64encode(arr.tobytes()).decode("ascii")
        else:
            emb_compressed = ""

        return {
            "sighting_id": self.sighting_id,
            "camera_id": self.camera_id,
            "ts": self.ts,
            "embedding_b64": emb_compressed,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "matched_person_id": self.matched_person_id,
            "match_score": self.match_score,
            "image_path": self.image_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FaceSighting':
        """Create from dictionary. Handles both base64 and legacy JSON formats."""
        import base64

        # Decompress embedding
        if "embedding_b64" in data and data["embedding_b64"]:
            raw = base64.b64decode(data["embedding_b64"])
            embedding = np.frombuffer(raw, dtype=np.float16).astype(np.float32).tolist()
        elif "embedding" in data:
            embedding = data["embedding"]  # Legacy JSON float list
        else:
            embedding = []

        return cls(
            sighting_id=data["sighting_id"],
            camera_id=data["camera_id"],
            ts=data["ts"],
            embedding=embedding,
            bbox=tuple(data["bbox"]),
            confidence=data["confidence"],
            matched_person_id=data.get("matched_person_id"),
            match_score=data.get("match_score"),
            image_path=data.get("image_path"),
            metadata=data.get("metadata", {}),
        )


class FaceSightingStore:
    """
    JSONL-based storage for face sightings.

    Stores every detected face (not just watchlist matches) for
    retrospective search, cross-camera tracking, and pattern analysis.
    """

    def __init__(self, storage_path: str = "alibi/data/face_sightings.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()

        if not self.storage_path.exists():
            self.storage_path.touch()
            print(f"[FaceSightingStore] Created new sightings file: {self.storage_path}")

    def add_sighting(self, sighting: FaceSighting) -> None:
        """Add a face sighting to the store (encrypted at rest)."""
        self._crypto.write_line(self.storage_path, sighting.to_dict())

    def load_all(self, limit: Optional[int] = None) -> List[FaceSighting]:
        """Load all sightings (or limited number, most recent).

        LAST WRITE WINS per sighting_id. The file is append-only, so correcting
        a sighting — clearing a name off a face that turned out to be someone
        else — writes a new row rather than editing the old one. Returning both
        meant the correction was invisible: the stale row still carried the
        wrong name, and the face stayed labelled after being un-named.
        """
        by_id = {}
        order = []
        if not self.storage_path.exists():
            return []

        for data in self._crypto.read_lines(self.storage_path):
            try:
                sighting = FaceSighting.from_dict(data)
            except Exception as e:
                print(f"[FaceSightingStore] Error loading sighting: {e}")
                continue
            if sighting.sighting_id not in by_id:
                order.append(sighting.sighting_id)
            by_id[sighting.sighting_id] = sighting

        sightings = [by_id[sid] for sid in order]

        if limit and len(sightings) > limit:
            sightings = sightings[-limit:]

        return sightings

    def get_by_camera(self, camera_id: str, limit: int = 100) -> List[FaceSighting]:
        """Get sightings for a specific camera."""
        all_sightings = self.load_all()
        matches = [s for s in all_sightings if s.camera_id == camera_id]
        matches.sort(key=lambda s: s.ts, reverse=True)
        return matches[:limit]

    def get_by_timerange(
        self,
        from_ts: str,
        to_ts: str,
        camera_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[FaceSighting]:
        """Get sightings within a time range."""
        all_sightings = self.load_all()
        matches = []

        for s in all_sightings:
            try:
                sighting_time = datetime.fromisoformat(s.ts)
                from_time = datetime.fromisoformat(from_ts)
                to_time = datetime.fromisoformat(to_ts)

                if from_time <= sighting_time <= to_time:
                    if camera_id is None or s.camera_id == camera_id:
                        matches.append(s)
            except Exception:
                continue

        matches.sort(key=lambda s: s.ts, reverse=True)
        return matches[:limit]

    def find_similar(
        self,
        query_embedding: np.ndarray,
        threshold: float = 0.6,
        limit: int = 50,
    ) -> List[Tuple[FaceSighting, float]]:
        """
        Find sightings with face embeddings similar to the query.

        Uses cosine similarity. Returns (sighting, score) tuples
        sorted by score descending, above threshold.

        Performance: linear scan over all stored embeddings.
        At 128-d float32, 10K sightings is ~5MB — fine for JSONL scale.
        """
        all_sightings = self.load_all()
        if not all_sightings:
            return []

        # Normalize query
        query = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(query)
        if q_norm == 0:
            return []
        query = query / q_norm

        results = []
        for s in all_sightings:
            try:
                emb = np.array(s.embedding, dtype=np.float32)
                e_norm = np.linalg.norm(emb)
                if e_norm == 0:
                    continue
                emb = emb / e_norm

                score = float(np.dot(query, emb))
                if score >= threshold:
                    results.append((s, score))
            except Exception:
                continue

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def get_recent(self, limit: int = 100) -> List[FaceSighting]:
        """Get most recent sightings."""
        all_sightings = self.load_all()
        all_sightings.sort(key=lambda s: s.ts, reverse=True)
        return all_sightings[:limit]

    def count(self) -> int:
        """Get total number of sightings."""
        return len(self.load_all())


# ── Global singleton ───────────────────────────────────────────

_store: Optional[FaceSightingStore] = None


def get_face_sighting_store() -> FaceSightingStore:
    """Get the global FaceSightingStore instance."""
    global _store
    if _store is None:
        _store = FaceSightingStore()
    return _store
