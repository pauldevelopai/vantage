"""
Vantage Site Profile — WHAT a deployment is protecting, and how the
intelligence layer is tailored to it.

A *site* is the subject Vantage watches over: a **home**, an **office**, or a
**neighbourhood**. The subject type changes what "normal" looks like and what
merits a reviewer's attention, so every downstream intelligence step — the
"why flagged" explainer, the area-context lookup, the pattern engine, and the
security brief — keys off the site's profile and its built-in *posture*.

SAFETY POSTURE (identical to the rest of Vantage):
  * A posture describes the PLACE and its normal rhythms, and names SITUATIONS
    that merit a human look (a presence at the perimeter after hours; a vehicle
    dwelling at a boundary). It never describes or accuses a person.
  * Area context is background about the place, never evidence about anyone in
    frame.
  * A trigger raises "worth a human review", never "this is a threat".

The store is JSON-backed and mutable (profiles get edited), mirroring the
camera BridgeRegistry rather than the append-only intelligence log.
"""

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SUBJECT_TYPES = ("home", "office", "neighbourhood")

DEFAULT_STORE_PATH = "alibi/data/site_profiles.json"


# --------------------------------------------------------------------------- #
# Posture — the per-subject-type tailoring of the intelligence layer.
# --------------------------------------------------------------------------- #

@dataclass
class Posture:
    """How the intelligence layer is tuned for a subject type.

    `focus` / `normal` / `review_triggers` are grounded, situational, and
    non-accusatory; `brief_sections` drives what the continuous security brief
    reports on for this kind of site.
    """
    subject_type: str
    label: str
    summary: str
    focus: List[str]            # what the intelligence weights for this site
    normal: List[str]           # baseline expected activity (anomaly = deviation)
    review_triggers: List[str]  # SITUATIONS that merit a human look (never accusations)
    brief_sections: List[str]   # sections the continuous security brief covers


POSTURES: Dict[str, Posture] = {
    "home": Posture(
        subject_type="home",
        label="Home",
        summary=(
            "Residential. Weighs perimeter and access points, and activity "
            "outside the household's normal daily rhythm."
        ),
        focus=[
            "perimeter and boundary (wall, fence, gate)",
            "access points (front door, driveway, garage)",
            "after-hours presence around the property",
            "vehicles stationary at or near the boundary",
        ],
        normal=[
            "residents and known vehicles arriving and leaving",
            "daytime deliveries and brief presence at the door",
            "scheduled services (refuse, garden, pool)",
        ],
        review_triggers=[
            "presence at the perimeter outside normal hours",
            "extended dwell at an entry point without approaching the door",
            "repeated passes of the property in a short window",
            "an unfamiliar vehicle stationary at the boundary for an extended period",
        ],
        brief_sections=[
            "perimeter coverage",
            "after-hours activity",
            "entry-point dwell events",
            "unfamiliar-vehicle notes",
            "area context (background)",
        ],
    ),
    "office": Posture(
        subject_type="office",
        label="Office / business",
        summary=(
            "Commercial premises. Weighs access control, out-of-hours presence, "
            "and service/loading areas against the opening routine."
        ),
        focus=[
            "entrances and access control",
            "presence during closed hours and weekends",
            "loading and service areas",
            "vehicle movements on the premises",
            "adherence to the opening/closing routine",
        ],
        normal=[
            "staff and visitors during business hours",
            "deliveries at the loading area within delivery windows",
            "predictable opening and closing",
        ],
        review_triggers=[
            "presence on the premises during closed hours",
            "activity at service or loading areas outside delivery windows",
            "a vehicle in a restricted or staff-only area",
            "access attempts that fall outside the normal routine",
        ],
        brief_sections=[
            "after-hours and weekend activity",
            "access-point events",
            "loading-bay events",
            "vehicle movements",
            "routine deviations",
            "area context (background)",
        ],
    ),
    "neighbourhood": Posture(
        subject_type="neighbourhood",
        label="Neighbourhood",
        summary=(
            "Area-wide watch across many cameras. Weighs correlations between "
            "properties and area-wide movement patterns over time."
        ),
        focus=[
            "the same unfamiliar vehicle or person appearing across properties",
            "movement patterns between properties",
            "slow or repeated passes along the road",
            "presence at multiple boundaries in a short window",
            "area-wide activity trend over time",
        ],
        normal=[
            "residents and their regular vehicles",
            "regular services (refuse, post, deliveries)",
            "through-traffic on the road",
        ],
        review_triggers=[
            "an unfamiliar vehicle or person seen across several properties in a short window",
            "slow repeated passes covering multiple properties",
            "presence at more than one boundary in close succession",
            "a cluster of after-hours perimeter events across the area",
        ],
        brief_sections=[
            "cross-property correlations",
            "repeated appearances",
            "movement patterns",
            "area activity trend",
            "shared alerts",
        ],
    ),
}


def normalize_subject_type(subject_type: Optional[str]) -> str:
    """Map free input to a known subject type, defaulting to 'home'."""
    st = (subject_type or "").strip().lower()
    if st in POSTURES:
        return st
    # tolerant aliases
    if st in ("house", "residence", "residential", "apartment", "flat"):
        return "home"
    if st in ("business", "commercial", "shop", "store", "warehouse", "workplace"):
        return "office"
    if st in ("area", "estate", "complex", "street", "community", "watch"):
        return "neighbourhood"
    return "home"


def posture_for(subject_type: Optional[str]) -> Posture:
    """Return the built-in posture for a subject type (never raises)."""
    return POSTURES[normalize_subject_type(subject_type)]


# --------------------------------------------------------------------------- #
# SiteProfile — the mutable, user-owned record of a protected site.
# --------------------------------------------------------------------------- #

@dataclass
class SiteProfile:
    site_id: str
    name: str
    subject_type: str                       # one of SUBJECT_TYPES
    area: str = ""                           # suburb/area — links to data-engine area context
    address: str = ""                        # optional, free text
    timezone: str = "Africa/Johannesburg"
    normal_hours: Dict[str, Any] = field(default_factory=dict)  # e.g. {"open": "07:00", "close": "18:00"}
    camera_ids: List[str] = field(default_factory=list)         # cameras scoped to this site
    notes: str = ""
    context: str = ""                        # free-text intelligence context for the AI:
    # who's normally here, known vehicles, routines, specific concerns.
    created_at: str = ""
    updated_at: str = ""

    def posture(self) -> Posture:
        return posture_for(self.subject_type)


class SiteProfileStore:
    """JSON-backed store of site profiles (mutable; small set)."""

    def __init__(self, storage_path: str = DEFAULT_STORE_PATH):
        self.path = Path(storage_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sites: Dict[str, SiteProfile] = {}
        self._load()

    # -- persistence -------------------------------------------------------- #

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text() or "{}")
        except (json.JSONDecodeError, OSError):
            return
        for sid, data in (raw.get("sites") or {}).items():
            try:
                self._sites[sid] = SiteProfile(**data)
            except TypeError:
                continue

    def _save(self) -> None:
        payload = {"sites": {sid: asdict(s) for sid, s in self._sites.items()}}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.path)

    # -- CRUD --------------------------------------------------------------- #

    def create(
        self,
        name: str,
        subject_type: str,
        area: str = "",
        address: str = "",
        timezone: str = "Africa/Johannesburg",
        normal_hours: Optional[Dict[str, Any]] = None,
        camera_ids: Optional[List[str]] = None,
        notes: str = "",
        context: str = "",
        now: Optional[datetime] = None,
    ) -> SiteProfile:
        now = now or datetime.utcnow()
        ts = now.isoformat()
        site = SiteProfile(
            site_id="site_" + uuid.uuid4().hex[:12],
            name=name.strip() or "Untitled site",
            subject_type=normalize_subject_type(subject_type),
            area=area.strip(),
            address=address.strip(),
            timezone=timezone or "Africa/Johannesburg",
            normal_hours=normal_hours or {},
            camera_ids=list(camera_ids or []),
            notes=notes,
            context=context,
            created_at=ts,
            updated_at=ts,
        )
        self._sites[site.site_id] = site
        self._save()
        return site

    def get(self, site_id: str) -> Optional[SiteProfile]:
        return self._sites.get(site_id)

    def list(self) -> List[SiteProfile]:
        return sorted(self._sites.values(), key=lambda s: s.created_at)

    def update(self, site_id: str, now: Optional[datetime] = None, **fields) -> Optional[SiteProfile]:
        site = self._sites.get(site_id)
        if not site:
            return None
        allowed = {
            "name", "subject_type", "area", "address",
            "timezone", "normal_hours", "camera_ids", "notes", "context",
        }
        for key, val in fields.items():
            if key not in allowed or val is None:
                continue
            if key == "subject_type":
                val = normalize_subject_type(val)
            setattr(site, key, val)
        site.updated_at = (now or datetime.utcnow()).isoformat()
        self._save()
        return site

    def delete(self, site_id: str) -> bool:
        if site_id in self._sites:
            del self._sites[site_id]
            self._save()
            return True
        return False

    def posture(self, site_id: str) -> Optional[Posture]:
        site = self._sites.get(site_id)
        return site.posture() if site else None


_store: Optional[SiteProfileStore] = None


def get_site_profile_store() -> SiteProfileStore:
    """Global site-profile store."""
    global _store
    if _store is None:
        _store = SiteProfileStore()
    return _store
