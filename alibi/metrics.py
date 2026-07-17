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
        """Real KPIs over the window, read through the REAL stores.

        The old version counted raw lines in JSONL files — but those files are
        encrypted at rest, so every count was silently zero and the Metrics
        page sat dormant while the system was busy. Each section degrades
        independently to honest zeros."""
        cutoff = datetime.utcnow() - _parse_range(range_str)
        out: Dict[str, Any] = {
            "range": range_str,
            "generated_at": datetime.utcnow().isoformat(),
            "total_incidents": 0,
            "dismissed_rate": 0.0,
            "escalation_rate": 0.0,
            "avg_time_to_decision": None,
            "top_cameras": [],
            "top_zones": [],
            "vehicle_sightings": 0,
            "face_sightings": 0,
        }

        try:
            from alibi.alibi_store import get_store
            store = get_store()

            incidents = [i for i in store.list_incidents(limit=2000)
                         if getattr(i, "created_ts", None) and i.created_ts >= cutoff]
            out["total_incidents"] = len(incidents)
            if incidents:
                statuses = [getattr(i.status, "value", str(i.status)) for i in incidents]
                out["dismissed_rate"] = round(statuses.count("dismissed") / len(incidents), 3)
                out["escalation_rate"] = round(statuses.count("escalated") / len(incidents), 3)

            # Time-to-decision: decision ts minus its incident's creation.
            created = {i.incident_id: i.created_ts for i in incidents}
            deltas = []
            try:
                for d in store.list_decisions(limit=2000):
                    c = created.get(d.incident_id)
                    if c is not None and d.decision_ts >= c:
                        deltas.append((d.decision_ts - c).total_seconds() / 60.0)
            except Exception:
                pass
            if deltas:
                out["avg_time_to_decision"] = round(sum(deltas) / len(deltas), 1)

            cam_counts: Dict[str, int] = {}
            zone_counts: Dict[str, int] = {}
            for e in store.list_events(limit=5000):
                if getattr(e, "ts", None) and e.ts >= cutoff:
                    cam_counts[e.camera_id] = cam_counts.get(e.camera_id, 0) + 1
                    if getattr(e, "zone_id", None):
                        zone_counts[e.zone_id] = zone_counts.get(e.zone_id, 0) + 1
            out["top_cameras"] = [{"camera_id": c, "count": n} for c, n in
                                  sorted(cam_counts.items(), key=lambda kv: -kv[1])[:5]]
            out["top_zones"] = [{"zone_id": z, "count": n} for z, n in
                                sorted(zone_counts.items(), key=lambda kv: -kv[1])[:5]]
        except Exception:
            pass

        cutoff_iso = cutoff.isoformat()
        try:
            from alibi.vehicles.sightings_store import VehicleSightingsStore
            out["vehicle_sightings"] = sum(
                1 for s in VehicleSightingsStore().load_all() if s.ts >= cutoff_iso)
        except Exception:
            pass
        try:
            from alibi.watchlist.face_sighting_store import get_face_sighting_store
            out["face_sightings"] = sum(
                1 for s in get_face_sighting_store().load_all() if s.ts >= cutoff_iso)
        except Exception:
            pass
        return out


_aggregator_instance: Optional[MetricsAggregator] = None


def get_metrics_aggregator() -> MetricsAggregator:
    """Get or create the global metrics aggregator."""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = MetricsAggregator()
    return _aggregator_instance
