"""
Vantage Data Engine — core schemas (§9).

Every ingested record is provenance-, lawful-basis- and retention-tagged BY
CONSTRUCTION: you cannot build an IngestRecord without them. This is the §8
lawful-data boundary expressed in types rather than in a policy doc.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class DataDomain(str, Enum):
    """The ONLY domains this engine is allowed to ingest (see §9).

    Personal-data / people-dossier ingestion is deliberately absent — there is
    no enum member for it, so a source cannot even be declared for it.
    """
    PLACES_CONTEXT = "places_context"        # crime stats, risk, POI, geo, weather
    DETECTION_REFERENCE = "detection_reference"  # make/model, plate rules, official registries


class LawfulBasis(str, Enum):
    """Why we are lawfully allowed to hold this record (POPIA/GDPR-aligned)."""
    PUBLIC_INTEREST_STATISTICS = "public_interest_statistics"  # e.g. published crime stats
    PUBLICLY_AVAILABLE_REFERENCE = "publicly_available_reference"  # e.g. make/model catalog
    OFFICIAL_REGISTRY = "official_registry"  # e.g. official stolen-vehicle registry
    LEGITIMATE_INTEREST_NON_PERSONAL = "legitimate_interest_non_personal"


@dataclass(frozen=True)
class SourceSpec:
    """Declares an ingestion source. The lawful basis and retention are part of
    the declaration — a source cannot be registered without them."""
    source_id: str                  # e.g. "places.sa_crime_stats"
    domain: DataDomain
    lawful_basis: LawfulBasis
    retention_days: int
    description: str
    apify_actor: Optional[str] = None   # e.g. "apify/website-content-crawler"
    actor_input: Dict[str, Any] = field(default_factory=dict)
    # Maps one raw Apify dataset item -> a normalised payload dict (or None to skip)
    normaliser: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None

    def __post_init__(self):
        if self.retention_days <= 0:
            raise ValueError("retention_days must be positive — records must expire")


@dataclass
class IngestRecord:
    """A single normalised, tagged record in the data engine store."""
    record_id: str
    source_id: str
    domain: DataDomain
    lawful_basis: LawfulBasis
    ingested_at: datetime
    retention_until: datetime
    payload: Dict[str, Any] = field(default_factory=dict)
    # Where it actually came from — the citation for anything Vantage asserts.
    provenance: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return (now or datetime.utcnow()) >= self.retention_until

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["domain"] = self.domain.value
        d["lawful_basis"] = self.lawful_basis.value
        d["ingested_at"] = self.ingested_at.isoformat()
        d["retention_until"] = self.retention_until.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IngestRecord":
        return cls(
            record_id=d["record_id"],
            source_id=d["source_id"],
            domain=DataDomain(d["domain"]),
            lawful_basis=LawfulBasis(d["lawful_basis"]),
            ingested_at=datetime.fromisoformat(d["ingested_at"]),
            retention_until=datetime.fromisoformat(d["retention_until"]),
            payload=d.get("payload", {}),
            provenance=d.get("provenance", {}),
        )


def build_record(
    record_id: str,
    spec: SourceSpec,
    payload: Dict[str, Any],
    provenance: Dict[str, Any],
    now: Optional[datetime] = None,
) -> IngestRecord:
    """Construct a record with retention derived from its source declaration."""
    now = now or datetime.utcnow()
    return IngestRecord(
        record_id=record_id,
        source_id=spec.source_id,
        domain=spec.domain,
        lawful_basis=spec.lawful_basis,
        ingested_at=now,
        retention_until=now + timedelta(days=spec.retention_days),
        payload=payload,
        provenance=provenance,
    )
