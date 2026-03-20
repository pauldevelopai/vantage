"""
Activity Baseline Engine

Per-camera hourly pattern learning and z-score anomaly detection.
Learns what's "normal" for each camera at each hour/day and flags
observations that deviate significantly from the baseline.
"""

import json
import math
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

from alibi.encryption import get_encrypted_writer


BASELINES_PATH = Path("alibi/data/activity_baselines.jsonl")
ANOMALIES_PATH = Path("alibi/data/anomaly_scores.jsonl")

# Ensure directories exist
BASELINES_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class ActivityBaseline:
    """Per-camera, per-hour, per-day-of-week activity baseline."""
    camera_id: str
    hour_of_day: int           # 0-23
    day_of_week: int           # 0=Mon, 6=Sun
    avg_person_count: float
    avg_vehicle_count: float
    avg_threat_level: float    # 0.0 = safe, 1.0 = critical
    std_person_count: float
    std_vehicle_count: float
    std_threat_level: float
    sample_count: int
    last_updated: str          # ISO timestamp

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ActivityBaseline':
        return cls(**data)


@dataclass
class AnomalyScore:
    """Result of scoring an observation against a baseline."""
    camera_id: str
    timestamp: str
    person_z_score: float
    vehicle_z_score: float
    threat_z_score: float
    combined_score: float      # max of absolute z-scores
    is_anomalous: bool         # combined_score > threshold
    baseline_sample_count: int

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'AnomalyScore':
        return cls(**data)


# Threat level string → numeric mapping
_THREAT_MAP = {
    "safe": 0.0,
    "caution": 0.33,
    "warning": 0.67,
    "critical": 1.0,
}

# Object types that count as "vehicle"
_VEHICLE_TYPES = {"car", "truck", "motorcycle", "bus", "van", "bakkie"}


class ActivityBaselineEngine:
    """
    Builds per-camera activity baselines from historical camera analysis
    and scores current observations for anomalies using z-scores.
    """

    def __init__(
        self,
        baselines_path: str = None,
        anomalies_path: str = None,
        min_samples: int = 5,
        anomaly_threshold: float = 2.0,
    ):
        self._baselines_path = Path(baselines_path) if baselines_path else BASELINES_PATH
        self._anomalies_path = Path(anomalies_path) if anomalies_path else ANOMALIES_PATH
        self._baselines_path.parent.mkdir(parents=True, exist_ok=True)
        self._anomalies_path.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()
        self._min_samples = min_samples
        self._anomaly_threshold = anomaly_threshold

        # In-memory cache of baselines (loaded lazily)
        self._cache: Dict[str, ActivityBaseline] = {}
        self._cache_loaded = False

    def _cache_key(self, camera_id: str, hour: int, dow: int) -> str:
        return f"{camera_id}:{hour}:{dow}"

    def _ensure_cache(self):
        """Load baselines into memory cache."""
        if self._cache_loaded:
            return
        self._cache_loaded = True
        self._cache.clear()

        if not self._baselines_path.exists():
            return

        for data in self._crypto.read_lines(self._baselines_path):
            try:
                b = ActivityBaseline.from_dict(data)
                key = self._cache_key(b.camera_id, b.hour_of_day, b.day_of_week)
                self._cache[key] = b
            except Exception:
                continue

    def build_baselines(self, camera_id: Optional[str] = None, days: int = 7) -> int:
        """
        Build or rebuild activity baselines from camera analysis history.

        Args:
            camera_id: Specific camera to rebuild (None = all cameras)
            days: Number of days of history to use

        Returns:
            Number of baseline records written
        """
        from alibi.camera_analysis_store import get_camera_analysis_store

        store = get_camera_analysis_store()
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        analyses = store.get_by_date_range(start, end)

        if camera_id:
            analyses = [a for a in analyses if a.camera_source == camera_id]

        if not analyses:
            print(f"[BaselineEngine] No analyses found for last {days} days")
            return 0

        # Group by (camera, hour, day_of_week)
        buckets: Dict[str, List[Dict]] = defaultdict(list)

        for a in analyses:
            try:
                ts = datetime.fromisoformat(a.timestamp.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue

            key = self._cache_key(a.camera_source, ts.hour, ts.weekday())

            person_count = sum(1 for obj in a.detected_objects if obj.lower() == "person")
            vehicle_count = sum(1 for obj in a.detected_objects if obj.lower() in _VEHICLE_TYPES)
            threat_numeric = _THREAT_MAP.get(
                (a.metadata or {}).get("threat_level", "safe"), 0.0
            )

            buckets[key].append({
                "persons": person_count,
                "vehicles": vehicle_count,
                "threat": threat_numeric,
            })

        # Compute stats for each bucket
        baselines: List[ActivityBaseline] = []
        now_iso = datetime.utcnow().isoformat()

        for key, observations in buckets.items():
            parts = key.split(":")
            cam = parts[0]
            hour = int(parts[1])
            dow = int(parts[2])
            n = len(observations)

            persons = [o["persons"] for o in observations]
            vehicles = [o["vehicles"] for o in observations]
            threats = [o["threat"] for o in observations]

            baselines.append(ActivityBaseline(
                camera_id=cam,
                hour_of_day=hour,
                day_of_week=dow,
                avg_person_count=_mean(persons),
                avg_vehicle_count=_mean(vehicles),
                avg_threat_level=_mean(threats),
                std_person_count=_std(persons),
                std_vehicle_count=_std(vehicles),
                std_threat_level=_std(threats),
                sample_count=n,
                last_updated=now_iso,
            ))

        # Write baselines (overwrite file)
        # If building for a specific camera, preserve other cameras' baselines
        if camera_id:
            existing = self.get_all_baselines()
            other_baselines = [b for b in existing if b.camera_id != camera_id]
            baselines = other_baselines + baselines

        # Write all baselines to file
        if self._baselines_path.exists():
            self._baselines_path.unlink()
        self._baselines_path.touch()

        for b in baselines:
            self._crypto.write_line(self._baselines_path, b.to_dict())

        # Refresh cache
        self._cache_loaded = False
        self._ensure_cache()

        print(f"[BaselineEngine] Built {len(baselines)} baselines from {len(analyses)} analyses")
        return len(baselines)

    def get_baseline(self, camera_id: str, hour: int, day_of_week: int) -> Optional[ActivityBaseline]:
        """Get the baseline for a specific camera/hour/day combination."""
        self._ensure_cache()
        key = self._cache_key(camera_id, hour, day_of_week)
        return self._cache.get(key)

    def get_all_baselines(self, camera_id: Optional[str] = None) -> List[ActivityBaseline]:
        """Load all baselines, optionally filtered by camera."""
        self._ensure_cache()
        baselines = list(self._cache.values())
        if camera_id:
            baselines = [b for b in baselines if b.camera_id == camera_id]
        return baselines

    def score_observation(
        self,
        camera_id: str,
        person_count: int,
        vehicle_count: int,
        threat_level: str,
        timestamp: Optional[datetime] = None,
    ) -> AnomalyScore:
        """
        Score a current observation against the baseline for this camera/time.

        Returns an AnomalyScore with z-scores and anomaly flag.
        If no baseline exists or sample_count < min_samples, returns neutral score.
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        baseline = self.get_baseline(camera_id, timestamp.hour, timestamp.weekday())

        if baseline is None or baseline.sample_count < self._min_samples:
            return AnomalyScore(
                camera_id=camera_id,
                timestamp=timestamp.isoformat(),
                person_z_score=0.0,
                vehicle_z_score=0.0,
                threat_z_score=0.0,
                combined_score=0.0,
                is_anomalous=False,
                baseline_sample_count=baseline.sample_count if baseline else 0,
            )

        threat_numeric = _THREAT_MAP.get(threat_level, 0.0)

        person_z = _z_score(person_count, baseline.avg_person_count, baseline.std_person_count)
        vehicle_z = _z_score(vehicle_count, baseline.avg_vehicle_count, baseline.std_vehicle_count)
        threat_z = _z_score(threat_numeric, baseline.avg_threat_level, baseline.std_threat_level)

        combined = max(abs(person_z), abs(vehicle_z), abs(threat_z))
        is_anomalous = combined > self._anomaly_threshold

        score = AnomalyScore(
            camera_id=camera_id,
            timestamp=timestamp.isoformat(),
            person_z_score=round(person_z, 3),
            vehicle_z_score=round(vehicle_z, 3),
            threat_z_score=round(threat_z, 3),
            combined_score=round(combined, 3),
            is_anomalous=is_anomalous,
            baseline_sample_count=baseline.sample_count,
        )

        # Persist anomaly scores
        try:
            self._crypto.write_line(self._anomalies_path, score.to_dict())
        except Exception:
            pass

        return score

    def get_recent_anomalies(self, hours: int = 24, threshold: Optional[float] = None) -> List[AnomalyScore]:
        """Get recent anomaly scores above threshold."""
        if threshold is None:
            threshold = self._anomaly_threshold

        cutoff = datetime.utcnow() - timedelta(hours=hours)
        results = []

        if not self._anomalies_path.exists():
            return results

        for data in self._crypto.read_lines(self._anomalies_path):
            try:
                score = AnomalyScore.from_dict(data)
                ts = datetime.fromisoformat(score.timestamp.replace('Z', '+00:00'))
                if ts >= cutoff and score.combined_score >= threshold:
                    results.append(score)
            except Exception:
                continue

        results.sort(key=lambda s: s.combined_score, reverse=True)
        return results


# ── Helper functions ───────────────────────────────────────────

def _mean(values: List[float]) -> float:
    """Mean of a list."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def _z_score(value: float, mean: float, std: float) -> float:
    """Z-score. Returns 0 if std is 0 (no variance)."""
    if std == 0.0:
        return 0.0
    return (value - mean) / std


# ── Global singleton ───────────────────────────────────────────

_engine: Optional[ActivityBaselineEngine] = None


def get_baseline_engine() -> ActivityBaselineEngine:
    """Get the global ActivityBaselineEngine instance."""
    global _engine
    if _engine is None:
        _engine = ActivityBaselineEngine()
    return _engine
