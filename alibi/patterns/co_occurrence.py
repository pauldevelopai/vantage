"""
Co-occurrence — "this vehicle/person was near N incidents."

The concept note's core example: a vehicle seen near three incidents in one week
is three unconnected records, not one pattern. This links an entity's sightings
(plate / person) to incidents that happened at the same camera within a short
time window — surfacing a pattern an operator can then investigate.

No-Accuse: this reports proximity in space + time, nothing more. Being near an
incident is not involvement; it is a lead for a human to follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Iterable

from alibi.alibi_store import get_store


@dataclass
class CoOccurrenceHit:
    incident_id: str
    camera_id: str
    incident_ts: str
    sighting_ts: str
    gap_seconds: float


@dataclass
class CoOccurrenceResult:
    entity_label: str
    incident_count: int
    hits: List[CoOccurrenceHit] = field(default_factory=list)
    summary: str = ""


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def find_incidents_near(
    sightings: List[Tuple[str, datetime]],
    incidents: Iterable,
    window_minutes: float = 30.0,
) -> List[CoOccurrenceHit]:
    """
    Pure: incidents that share a camera with one of `sightings` within the
    window. At most one hit per incident (its closest matching event).

    Args:
        sightings: list of (camera_id, timestamp) for the entity.
        incidents: iterable of Incident (each with .events[camera_id, ts]).
    """
    window_s = timedelta(minutes=window_minutes).total_seconds()
    hits: List[CoOccurrenceHit] = []
    for inc in incidents:
        best = None
        for ev in getattr(inc, "events", []) or []:
            for cam, sts in sightings:
                if ev.camera_id != cam:
                    continue
                gap = abs((_naive(ev.ts) - _naive(sts)).total_seconds())
                if gap <= window_s and (best is None or gap < best[0]):
                    best = (gap, cam, ev.ts, sts)
        if best is not None:
            gap, cam, ets, sts = best
            hits.append(CoOccurrenceHit(
                incident_id=getattr(inc, "incident_id", ""),
                camera_id=cam,
                incident_ts=ets.isoformat(),
                sighting_ts=sts.isoformat(),
                gap_seconds=round(gap, 1),
            ))
    hits.sort(key=lambda h: h.incident_ts, reverse=True)
    return hits


class CoOccurrence:
    """Links entities to nearby incidents, backed by the incident store."""

    def __init__(self, incident_store=None):
        self.store = incident_store if incident_store is not None else get_store()

    def entity_incidents(
        self,
        sightings: List[Tuple[str, datetime]],
        window_minutes: float = 30.0,
        entity_label: str = "entity",
        incident_limit: int = 500,
    ) -> CoOccurrenceResult:
        incidents = self.store.list_incidents(limit=incident_limit)
        hits = find_incidents_near(sightings, incidents, window_minutes)
        return CoOccurrenceResult(
            entity_label=entity_label,
            incident_count=len(hits),
            hits=hits,
            summary=self._summarise(entity_label, hits, window_minutes),
        )

    def plate_incidents(self, plate: str, vehicle_store, window_minutes: float = 30.0) -> CoOccurrenceResult:
        """Convenience: co-occurrence for a plate's sightings."""
        sightings: List[Tuple[str, datetime]] = []
        for v in vehicle_store.search_by_plate(plate, limit=1000):
            try:
                sightings.append((v.camera_id, _naive(datetime.fromisoformat(str(v.ts).replace("Z", "+00:00")))))
            except (ValueError, TypeError):
                continue
        return self.entity_incidents(sightings, window_minutes, entity_label=f"plate {plate}")

    @staticmethod
    def _summarise(label: str, hits: List[CoOccurrenceHit], window_minutes: float) -> str:
        if not hits:
            return f"{label}: no incidents nearby."
        cams = sorted({h.camera_id for h in hits})
        return (f"Possible pattern: {label} was near {len(hits)} incident(s) "
                f"(within {int(window_minutes)} min, at {', '.join(cams)}) — for operator review.")
