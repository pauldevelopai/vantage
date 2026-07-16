"""
User-declared data sources — "feed the brain as you go".

The built-in `SOURCES` registry (sources.py) is code-declared. This is its mutable
sibling: sources the OWNER adds from the console as they gain access to them (an
official feed they've licensed, a reference list, area context they maintain).

The same discipline applies, deliberately:
  * a source must declare a `DataDomain` — and that enum has NO personal-data
    member, so a personal-dossier source cannot be declared even here;
  * it must declare a `LawfulBasis` — why we may lawfully hold it; and
  * it must declare a positive `retention_days` — records expire, always.

`CATALOGUE` below is the honest roadmap: real, researched routes to data we do NOT
have yet, each with what it would actually take. It is documentation, not data —
nothing in it is presented as connected, and the console renders it as such.
"""

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from alibi.dataengine.schemas import DataDomain, LawfulBasis

DEFAULT_STORE_PATH = "alibi/data/user_sources.json"


@dataclass
class UserSource:
    """A source the owner declared from the console."""
    source_id: str
    name: str
    domain: str                       # DataDomain value
    lawful_basis: str                 # LawfulBasis value
    retention_days: int
    description: str = ""
    endpoint: str = ""                # optional: a feed URL they've licensed
    notes: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    record_count: int = 0             # records fed in under this source

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_declaration(domain: str, lawful_basis: str, retention_days: int) -> Optional[str]:
    """Return an error string if the declaration breaks the engine's boundary.

    This is the gate that keeps the console honest: the UI cannot smuggle in a
    personal-data source, an undeclared lawful basis, or perpetual retention."""
    valid_domains = {d.value for d in DataDomain}
    if domain not in valid_domains:
        return (f"'{domain}' is not an allowed data domain. Vantage only ingests "
                f"non-personal data: {', '.join(sorted(valid_domains))}.")
    valid_bases = {b.value for b in LawfulBasis}
    if lawful_basis not in valid_bases:
        return (f"'{lawful_basis}' is not a recognised lawful basis. One of: "
                f"{', '.join(sorted(valid_bases))}.")
    try:
        rd = int(retention_days)
    except (TypeError, ValueError):
        return "retention_days must be a whole number of days."
    if rd <= 0:
        return "retention_days must be positive — records must expire."
    return None


class UserSourceStore:
    """JSON-backed, mutable store of owner-declared sources."""

    def __init__(self, storage_path: str = DEFAULT_STORE_PATH):
        self.path = Path(storage_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sources: Dict[str, UserSource] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text() or "{}")
        except (json.JSONDecodeError, OSError):
            return
        for sid, data in (raw.get("sources") or {}).items():
            try:
                self._sources[sid] = UserSource(**data)
            except TypeError:
                continue

    def _save(self) -> None:
        payload = {"sources": {sid: s.to_dict() for sid, s in self._sources.items()}}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.path)

    def add(self, name: str, domain: str, lawful_basis: str, retention_days: int,
            description: str = "", endpoint: str = "", notes: str = "",
            now: Optional[datetime] = None) -> UserSource:
        err = validate_declaration(domain, lawful_basis, retention_days)
        if err:
            raise ValueError(err)
        ts = (now or datetime.utcnow()).isoformat()
        src = UserSource(
            source_id="usrc_" + uuid.uuid4().hex[:10],
            name=name.strip() or "Untitled source",
            domain=domain, lawful_basis=lawful_basis,
            retention_days=int(retention_days),
            description=description.strip(), endpoint=endpoint.strip(),
            notes=notes.strip(), created_at=ts, updated_at=ts,
        )
        self._sources[src.source_id] = src
        self._save()
        return src

    def get(self, source_id: str) -> Optional[UserSource]:
        return self._sources.get(source_id)

    def list(self) -> List[UserSource]:
        return sorted(self._sources.values(), key=lambda s: s.created_at)

    def update(self, source_id: str, now: Optional[datetime] = None, **fields) -> Optional[UserSource]:
        src = self._sources.get(source_id)
        if not src:
            return None
        allowed = {"name", "description", "endpoint", "notes", "enabled", "retention_days"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(src, k, v)
        src.updated_at = (now or datetime.utcnow()).isoformat()
        self._save()
        return src

    def bump_records(self, source_id: str, n: int) -> None:
        src = self._sources.get(source_id)
        if src:
            src.record_count += n
            src.updated_at = datetime.utcnow().isoformat()
            self._save()

    def delete(self, source_id: str) -> bool:
        if source_id in self._sources:
            del self._sources[source_id]
            self._save()
            return True
        return False


_store: Optional[UserSourceStore] = None


def get_user_source_store() -> UserSourceStore:
    global _store
    if _store is None:
        _store = UserSourceStore()
    return _store


# --------------------------------------------------------------------------- #
# CATALOGUE — researched, real routes to data we do NOT have yet.
#
# This is a roadmap, not data. Every entry is something verified to exist, with
# what it would actually take to connect. Nothing here is presented as live.
# `status`: "available" (we could act today) | "gated" (needs a commercial or
# partner agreement) | "blocked" (a real route exists but is closed to us) |
# "rejected" (we could technically use it, and won't — with the reason).
# --------------------------------------------------------------------------- #

CATALOGUE: List[Dict[str, Any]] = [
    {
        "key": "navic",
        "name": "NAVIC — SAPS-sourced vehicle-of-interest feed",
        "provides": "Stolen / wanted vehicle plates (stated source: SAPS circulation / Unicode / ICB).",
        "why": "Would let a plate read at your gate be checked against the official stolen list.",
        "status": "gated",
        "requirement": "Partner/commercial agreement. NAVIC explicitly serves residential estates, farms and neighbourhood watches, and offers estate-level API integration. No public pricing — direct sales contact.",
        "url": "https://navic.cloud",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.OFFICIAL_REGISTRY.value,
        "recommended": True,
    },
    {
        "key": "vumacam",
        "name": "Vumacam — vehicle-of-interest feed",
        "provides": "Same SAPS-sourced VOI data, via the Eyes & Ears fusion centre.",
        "why": "The largest private ANPR network in SA; its partners consume the VOI list.",
        "status": "gated",
        "requirement": "Partner agreement, sales-gated with no published criteria or pricing. Partners include mid-size firms, so smaller players are not excluded in principle.",
        "url": "https://www.vumacam.co.za/partners",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.OFFICIAL_REGISTRY.value,
    },
    {
        "key": "transunion",
        "name": "TransUnion Auto Verifications (via Imagin8)",
        "provides": "Per-plate vehicle verification incl. a 'police interest' flag; database refreshed daily from SAPS.",
        "why": "The only route with published pricing and a real API that accepts a plate as the query key.",
        "status": "gated",
        "requirement": "Commercial account. Published pricing ~R1,685.85/month minimum, R14.24 → R1.08 per transaction. Confirm IN WRITING that 'police interest' returns a stolen flag and that ANPR use is contractually permitted.",
        "url": "https://imagin8.co.za/transunion-auto-data/",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.OFFICIAL_REGISTRY.value,
    },
    {
        "key": "owner_hotlist",
        "name": "Your own hotlist",
        "provides": "Plates you add yourself — a vehicle you're watching for, a known problem car.",
        "why": "Lawful, immediate, no dependency. The same store any official feed would later populate.",
        "status": "available",
        "requirement": "Nothing — add plates directly.",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.LEGITIMATE_INTEREST_NON_PERSONAL.value,
        "recommended": True,
    },
    {
        "key": "saps_crime_stats",
        "name": "SAPS published crime statistics",
        "provides": "Quarterly crime figures by police station / precinct.",
        "why": "Area context: what is actually common where this site is, so the brief reflects real local risk.",
        "status": "available",
        "requirement": "Published openly by SAPS. Needs an ingester + normaliser.",
        "url": "https://www.saps.gov.za/services/crimestats.php",
        "domain": DataDomain.PLACES_CONTEXT.value,
        "lawful_basis": LawfulBasis.PUBLIC_INTEREST_STATISTICS.value,
        "recommended": True,
    },
    {
        "key": "saia_vsd",
        "name": "SAIA Vehicle Salvage Database",
        "provides": "Write-off / salvage status by VIN (Code 2/3/3A/4).",
        "why": "Salvage history — NOT stolen. Useful context only; conflating the two would be a product error.",
        "status": "blocked",
        "requirement": "Free public web lookup, but VIN-only with no API, and covers under 3% of vehicles. ANPR reads plates, not VINs, so it cannot be wired to a camera.",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.PUBLICLY_AVAILABLE_REFERENCE.value,
    },
    {
        "key": "natis",
        "name": "NaTIS / eNaTIS vehicle register",
        "provides": "The authoritative plate → vehicle bridge.",
        "why": "This is the only lawful plate-keyed official record — which is exactly why it's closed.",
        "status": "blocked",
        "requirement": "Access is tied to statutory roles. No route exists for a private company. Treat any vendor claiming live NaTIS access as false or unlawful until proven.",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.OFFICIAL_REGISTRY.value,
    },
    {
        "key": "crowdsourced",
        "name": "Crowdsourced plate lists (NP Tracker, stolenvehicles.co.za)",
        "provides": "Free, plate-keyed 'suspect vehicle' lists with public APIs.",
        "why": "Technically the easiest to connect — and we are deliberately not connecting them.",
        "status": "rejected",
        "requirement": "NP Tracker's operator states the data is 'untrusted and unverified' and that lookout reports are published without verification; stolenvehicles.co.za's terms bar commercial use outright. A false 'stolen' flag raised against a real person at their gate is a physical-safety risk. Authoritative or nothing.",
        "domain": DataDomain.DETECTION_REFERENCE.value,
        "lawful_basis": LawfulBasis.PUBLICLY_AVAILABLE_REFERENCE.value,
    },
]
