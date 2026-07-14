"""
Activity Patterns — "what has been happening in the last hour / 24h / week?"

Aggregates the face- and vehicle-sighting archives over a time window into a
plain-English summary: how many people and vehicles, watchlist matches, plate
reads, which camera was busiest (hotspots), and the busiest time of day.

This is the Phase-2 "surfaces patterns" layer. It reports observed activity for
an operator to interpret — it does not accuse or predict guilt.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from alibi.watchlist.face_sighting_store import get_face_sighting_store
from alibi.vehicles.sightings_store import VehicleSightingsStore


# Named windows the UI offers.
WINDOWS = {"1h": 1.0, "24h": 24.0, "7d": 168.0, "week": 168.0}


def parse_window(window: str) -> float:
    """Parse '1h' / '24h' / '7d' / '30m' into hours (default 24h)."""
    w = (window or "24h").strip().lower()
    if w in WINDOWS:
        return WINDOWS[w]
    try:
        if w.endswith("h"):
            return float(w[:-1])
        if w.endswith("d"):
            return float(w[:-1]) * 24
        if w.endswith("m"):
            return float(w[:-1]) / 60
    except ValueError:
        pass
    return 24.0


@dataclass
class ActivitySummary:
    window: str
    from_ts: str
    to_ts: str
    people_sightings: int
    watchlist_matches: int
    vehicle_sightings: int
    plate_reads: int
    by_camera: Dict[str, int] = field(default_factory=dict)
    busiest_camera: Optional[str] = None
    by_hour: Dict[int, int] = field(default_factory=dict)
    busiest_hour: Optional[int] = None
    vehicle_colours: Dict[str, int] = field(default_factory=dict)
    narrative: str = ""


class ActivityPatterns:
    """Windowed aggregation over the sighting archives."""

    def __init__(self, face_store=None, vehicle_store=None):
        self.face_store = face_store if face_store is not None else get_face_sighting_store()
        self.vehicle_store = vehicle_store if vehicle_store is not None else VehicleSightingsStore()

    def summarize(self, window: str = "24h", now: Optional[datetime] = None) -> ActivitySummary:
        hours = parse_window(window)
        end = now or datetime.utcnow()
        start = end - timedelta(hours=hours)

        faces = [s for s in self.face_store.load_all() if _in_window(s.ts, start, end)]
        vehicles = [v for v in self.vehicle_store.load_all() if _in_window(v.ts, start, end)]

        by_camera: Counter = Counter()
        by_hour: Counter = Counter()
        for s in faces:
            by_camera[s.camera_id] += 1
            _bump_hour(by_hour, s.ts)
        for v in vehicles:
            by_camera[v.camera_id] += 1
            _bump_hour(by_hour, v.ts)

        watchlist_matches = sum(1 for s in faces if getattr(s, "matched_person_id", None))
        plate_reads = sum(1 for v in vehicles if (v.metadata or {}).get("plate_text"))
        colours = Counter(v.color for v in vehicles if v.color and v.color != "unknown")

        busiest_camera = by_camera.most_common(1)[0][0] if by_camera else None
        busiest_hour = by_hour.most_common(1)[0][0] if by_hour else None

        summary = ActivitySummary(
            window=window,
            from_ts=start.isoformat(), to_ts=end.isoformat(),
            people_sightings=len(faces),
            watchlist_matches=watchlist_matches,
            vehicle_sightings=len(vehicles),
            plate_reads=plate_reads,
            by_camera=dict(by_camera),
            busiest_camera=busiest_camera,
            by_hour={int(h): c for h, c in by_hour.items()},
            busiest_hour=busiest_hour,
            vehicle_colours=dict(colours),
            narrative="",
        )
        summary.narrative = self._narrate(summary)
        return summary

    @staticmethod
    def _narrate(s: ActivitySummary) -> str:
        if s.people_sightings == 0 and s.vehicle_sightings == 0:
            return f"No activity recorded in the last {s.window}."
        parts = [
            f"In the last {s.window}: {s.people_sightings} people sighting(s) "
            f"and {s.vehicle_sightings} vehicle sighting(s) ({s.plate_reads} plate read(s))."
        ]
        if s.watchlist_matches:
            parts.append(f"{s.watchlist_matches} possible watchlist match(es) — operator review required.")
        if s.busiest_camera:
            parts.append(f"Busiest camera: {s.busiest_camera}.")
        if s.busiest_hour is not None:
            parts.append(f"Most active around {s.busiest_hour:02d}:00.")
        return " ".join(parts)


def _in_window(ts: str, start: datetime, end: datetime) -> bool:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is not None:
            t = t.replace(tzinfo=None)
        return start <= t <= end
    except (ValueError, TypeError):
        return False


def _bump_hour(counter: Counter, ts: str) -> None:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        counter[t.hour] += 1
    except (ValueError, TypeError):
        pass
