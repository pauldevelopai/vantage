"""
Vantage Data Engine (§9) — lawful, non-personal external-data ingestion.

Pipeline: Apify actor -> normalise (allowlist) -> personal-data GUARD -> tagged
append-only store (source + lawful basis + retention + audit).

The §8 lawful-data boundary is enforced in code, not just documented:
  * `DataDomain` has no member for personal data — a source cannot be declared
    for it.
  * Normalisers are allowlist-based — undeclared fields are dropped.
  * `guard.assert_non_personal()` fail-closes on anything person-identifying.
"""

from alibi.dataengine.schemas import (
    DataDomain,
    LawfulBasis,
    SourceSpec,
    IngestRecord,
    build_record,
)
from alibi.dataengine.guard import (
    PersonalDataRejected,
    assert_non_personal,
    scan_for_personal_data,
)
from alibi.dataengine.store import DataEngineStore
from alibi.dataengine.apify import ApifyClient
from alibi.dataengine.ingest import IngestResult, ingest_items, run_source
from alibi.dataengine.sources import get_source, list_sources, register

__all__ = [
    "DataDomain",
    "LawfulBasis",
    "SourceSpec",
    "IngestRecord",
    "build_record",
    "PersonalDataRejected",
    "assert_non_personal",
    "scan_for_personal_data",
    "DataEngineStore",
    "ApifyClient",
    "IngestResult",
    "ingest_items",
    "run_source",
    "get_source",
    "list_sources",
    "register",
]
