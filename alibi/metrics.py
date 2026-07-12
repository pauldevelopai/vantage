"""
Metrics Aggregator

Computes dashboard KPI summaries from the system's own operational JSONL logs.
Real counts over a time window, honest zeros when there is no data yet.

Reconstructed to match the API used by alibi_api.py's /api/metrics/summary
endpoint: get_metrics_aggregator().compute_summary(range).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


def _parse_range(range_str: str) -> timedelta:
    """Parse '24h' / '7d' / '2w' into a timedelta (default 24h)."""
    s = (range_str or "24h").strip().lower()
    try:
        if s.endswith("h"):
            return timedelta(hours=float(s[:-1]))
        if s.endswith("d"):
            return timedelta(days=float(s[:-1]))
        if s.endswith("w"):
            return timedelta(weeks=float(s[:-1]))
        if s.endswith("m"):
            return timedelta(minutes=float(s[:-1]))
    except ValueError:
        pass
    return timedelta(hours=24)


class MetricsAggregator:
    """Aggregates KPI counts from the data-directory JSONL logs."""

    def __init__(self, data_dir: str = "alibi/data"):
        self.data_dir = Path(data_dir)

    def _count_recent(
        self,
        filename: str,
        cutoff: datetime,
        ts_keys: Tuple[str, ...] = ("timestamp", "ts", "created_ts"),
    ) -> int:
        """Count JSONL records whose timestamp is at/after cutoff. Records that
        can't be parsed (e.g. encrypted or malformed lines) are skipped."""
        path = self.data_dir / filename
        if not path.exists():
            return 0
        count = 0
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    ts = next((rec[k] for k in ts_keys if k in rec), None)
                    if ts is None:
                        continue
                    try:
                        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if t.tzinfo is not None:
                        t = t.replace(tzinfo=None)
                    if t >= cutoff:
                        count += 1
        except Exception as e:
            print(f"[MetricsAggregator] Error reading {path}: {e}")
        return count

    def compute_summary(self, range_str: str = "24h") -> Dict[str, Any]:
        """Return real KPI counts over the requested window."""
        cutoff = datetime.utcnow() - _parse_range(range_str)
        return {
            "range": range_str,
            "generated_at": datetime.utcnow().isoformat(),
            "incidents": self._count_recent("incident_processing.jsonl", cutoff),
            "analyses": self._count_recent("camera_analysis.jsonl", cutoff),
            "cross_camera_sightings": self._count_recent("cross_camera_sightings.jsonl", cutoff),
            "vehicle_sightings": self._count_recent("vehicle_sightings.jsonl", cutoff),
            "red_flags": self._count_recent("red_flags.jsonl", cutoff),
        }


_aggregator_instance: Optional[MetricsAggregator] = None


def get_metrics_aggregator() -> MetricsAggregator:
    """Get or create the global metrics aggregator."""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = MetricsAggregator()
    return _aggregator_instance
