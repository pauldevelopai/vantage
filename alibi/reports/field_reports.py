"""
Field reports — human observations from guards and people on the ground.

A guard logging "white bakkie, no plate, parked at the north gate ~02:00, left
after 20 min" is a first-class data source alongside the cameras. This store
holds those observations, append-only and encrypted at rest, and the Overview
surfaces them next to the camera sightings from the same window.

Honesty / POPIA posture (same as the rest of Vantage):
  * An observation is EVIDENCE from an identified person — kept and phrased
    situationally ("worth a look"), never a verdict, never an accusation.
  * No dossiers: a report about a named person is one logged observation, not a
    compiled profile.
  * Structured tags are optional and only what the observer supplied — we never
    infer a colour/type the reporter didn't state.

`build_report` (the normalise/validate) is pure and unit-tested; the store is a
thin encrypted-JSONL wrapper mirroring the sighting stores.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from alibi.encryption import get_encrypted_writer

SUBJECTS = ("person", "vehicle", "other")
VEHICLE_TYPES = ("", "car", "bakkie", "suv", "van", "truck", "minibus", "motorcycle")


@dataclass
class FieldReport:
    report_id: str
    ts: str                       # when the observation happened (ISO)
    logged_ts: str                # when it was filed
    observer: str                 # who filed it (name/role) — identified, not anon
    subject: str                  # person | vehicle | other
    note: str                     # the free-text observation
    camera_id: Optional[str] = None      # tie to a camera/location if known
    location: str = ""                   # free-text location if no camera
    tags: Dict[str, Any] = field(default_factory=dict)   # colour, vehicle_type, direction, plate
    source: str = "console"              # console | mobile

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FieldReport":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


def build_report(observer: str, subject: str, note: str,
                 camera_id: Optional[str] = None, location: str = "",
                 tags: Optional[Dict[str, Any]] = None, source: str = "console",
                 ts: Optional[str] = None, now: Optional[datetime] = None) -> FieldReport:
    """Validate + normalise a submission into a FieldReport. Pure. Raises
    ValueError on the things that make a report meaningless (no observer, no
    note, bad subject) — honest data only, never a half-empty row."""
    now = now or datetime.utcnow()
    observer = (observer or "").strip()
    note = (note or "").strip()
    subject = (subject or "").strip().lower()
    if not observer:
        raise ValueError("a report needs an observer (who saw it)")
    if not note:
        raise ValueError("a report needs a note (what was seen)")
    if subject not in SUBJECTS:
        raise ValueError(f"subject must be one of {SUBJECTS}")

    # Keep only tags the observer actually supplied; normalise the known ones.
    clean_tags: Dict[str, Any] = {}
    for k, v in (tags or {}).items():
        v = (str(v).strip() if v is not None else "")
        if not v:
            continue
        if k == "vehicle_type" and v.lower() not in VEHICLE_TYPES:
            continue
        clean_tags[k] = v.lower() if k in ("colour", "vehicle_type", "direction") else v

    return FieldReport(
        report_id=uuid.uuid4().hex[:16],
        ts=ts or now.isoformat(),
        logged_ts=now.isoformat(),
        observer=observer,
        subject=subject,
        note=note[:2000],
        camera_id=(camera_id or None),
        location=(location or "").strip()[:200],
        tags=clean_tags,
        source=source if source in ("console", "mobile") else "console",
    )


class FieldReportStore:
    def __init__(self, storage_path: str = "alibi/data/field_reports.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._crypto = get_encrypted_writer()

    def add(self, report: FieldReport) -> None:
        self._crypto.write_line(self.storage_path, report.to_dict())

    def list_recent(self, limit: int = 50, since_iso: Optional[str] = None) -> List[FieldReport]:
        if not self.storage_path.exists():
            return []
        rows: List[FieldReport] = []
        for d in self._crypto.read_lines(self.storage_path):
            try:
                r = FieldReport.from_dict(d)
            except (TypeError, KeyError):
                continue
            if since_iso and r.ts < since_iso:
                continue
            rows.append(r)
        rows.sort(key=lambda r: r.ts, reverse=True)
        return rows[:limit]


_store: Optional[FieldReportStore] = None


def get_field_report_store() -> FieldReportStore:
    global _store
    if _store is None:
        _store = FieldReportStore()
    return _store


def corroborating_sighting(report: FieldReport, vehicle_rows: List[Dict[str, Any]],
                           window_minutes: int = 20) -> Optional[Dict[str, Any]]:
    """Does a camera vehicle-sighting back up this vehicle report? A match is a
    same-camera sighting within the time window whose colour agrees (when the
    report gave one). This is CORROBORATION — "the camera also saw a vehicle
    here then" — never an identification. Pure."""
    if report.subject != "vehicle" or not report.camera_id:
        return None
    try:
        r_ts = datetime.fromisoformat(report.ts)
    except (ValueError, TypeError):
        return None
    want_colour = (report.tags or {}).get("colour")
    best = None
    for v in vehicle_rows:
        if v.get("camera_id") != report.camera_id or not v.get("ts"):
            continue
        try:
            v_ts = datetime.fromisoformat(v["ts"])
        except (ValueError, TypeError):
            continue
        if abs((v_ts - r_ts).total_seconds()) > window_minutes * 60:
            continue
        if want_colour and v.get("colour") and v["colour"].lower() != want_colour:
            continue
        best = {"event_id": v.get("event_id"), "ts": v.get("ts"),
                "colour": v.get("colour"), "camera_name": v.get("camera_name")}
        break
    return best
