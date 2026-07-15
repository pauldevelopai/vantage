"""
Vantage Data Engine — ingest orchestrator (§9).

Pipeline for every item:

    Apify actor -> normalise (allowlist) -> GUARD (reject personal data)
                -> tag (source + lawful basis + retention) -> append-only store
                -> audit

Rejections are counted and audited, never silently swallowed — if a source starts
emitting personal data you will see it in the result and the audit log.

Fail-safe: a source with no live Apify token yields an honest empty result
(fetched=0), never fabricated records.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from alibi.dataengine.apify import ApifyClient
from alibi.dataengine.guard import PersonalDataRejected, assert_non_personal
from alibi.dataengine.schemas import IngestRecord, SourceSpec, build_record
from alibi.dataengine.sources import get_source
from alibi.dataengine.store import DataEngineStore


@dataclass
class IngestResult:
    source_id: str
    fetched: int = 0
    stored: int = 0
    skipped: int = 0            # normaliser returned None (incomplete item)
    rejected_personal: int = 0  # blocked by the §8 guard
    rejections: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "fetched": self.fetched,
            "stored": self.stored,
            "skipped": self.skipped,
            "rejected_personal": self.rejected_personal,
            "rejections": self.rejections[:20],  # cap the noise
            "error": self.error,
        }


def _record_id(source_id: str, payload: Dict[str, Any]) -> str:
    """Stable id from the content, so re-running a source doesn't duplicate."""
    blob = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{source_id}:{blob}".encode()).hexdigest()[:16]
    return f"{source_id}:{digest}"


def ingest_items(
    spec: SourceSpec,
    items: List[Dict[str, Any]],
    store: DataEngineStore,
    now: Optional[datetime] = None,
    payload_extra: Optional[Dict[str, Any]] = None,
) -> IngestResult:
    """Normalise -> guard -> tag -> store a batch of raw items.

    This is the testable core: it takes items directly, so the pipeline can be
    exercised against fixtures without any network or Apify token.

    `payload_extra` is run-level provenance stamped onto every payload — e.g.
    `{"query_area": "Somerset West"}` records WHICH area a place was fetched
    for. Google's own `city` field is often the metro ("Cape Town" for a
    Somerset West clinic), so without this stamp the record can't be matched
    back to the camera area that requested it. Merged BEFORE the guard, so the
    guard scans the exact payload that gets stored.
    """
    result = IngestResult(source_id=spec.source_id)
    seen: set = set()

    for item in items:
        result.fetched += 1

        # 1. Normalise — allowlist; unknown fields (incl. any personal ones) dropped.
        payload = spec.normaliser(item) if spec.normaliser else dict(item)
        if not payload:
            result.skipped += 1
            continue
        if payload_extra:
            payload = {**payload, **payload_extra}

        # 2. GUARD — fail-closed on anything person-identifying that survived.
        try:
            assert_non_personal(payload)
        except PersonalDataRejected as e:
            result.rejected_personal += 1
            result.rejections.extend(e.violations)
            store.append_audit("rejected_personal_data", {
                "source_id": spec.source_id,
                "violations": e.violations,
            })
            continue

        # 3. Tag with provenance + lawful basis + retention, and store.
        rid = _record_id(spec.source_id, payload)
        if rid in seen:
            result.skipped += 1  # duplicate within this batch
            continue
        seen.add(rid)

        record = build_record(
            record_id=rid,
            spec=spec,
            payload=payload,
            provenance={
                "source_id": spec.source_id,
                "apify_actor": spec.apify_actor,
                "source_url": payload.get("source_url"),
                "fetched_at": (now or datetime.utcnow()).isoformat(),
            },
            now=now,
        )
        store.append(record)
        result.stored += 1

    store.append_audit("ingest_run", result.to_dict())
    return result


def run_source(
    source_id: str,
    store: Optional[DataEngineStore] = None,
    client: Optional[ApifyClient] = None,
    now: Optional[datetime] = None,
    input_overrides: Optional[Dict[str, Any]] = None,
    payload_extra: Optional[Dict[str, Any]] = None,
) -> IngestResult:
    """Run one declared source end-to-end via Apify. Never raises.

    `input_overrides` is merged over the source's declared `actor_input` for
    per-run parameters (e.g. which area to search). The source's safety-relevant
    input (reviews off, no personal data) stays in the declaration, so a caller
    cannot accidentally turn personal-data collection back on by forgetting it —
    they would have to override it explicitly.

    With no APIFY_TOKEN this returns an honest empty result rather than inventing
    data.
    """
    spec = get_source(source_id)
    if not spec:
        return IngestResult(source_id=source_id, error=f"unknown source '{source_id}'")

    store = store or DataEngineStore()
    client = client or ApifyClient()

    if not spec.apify_actor:
        return IngestResult(
            source_id=source_id,
            error="no Apify actor wired for this source yet",
        )

    actor_input = {**(spec.actor_input or {}), **(input_overrides or {})}

    items = client.run_actor_sync(spec.apify_actor, actor_input)
    if items is None:
        return IngestResult(source_id=source_id, error="Apify fetch failed or no token")

    return ingest_items(spec, items, store, now=now, payload_extra=payload_extra)


# What we harvest per area, in priority order. Emergency response first, then
# the activity anchors an analyst reads an area through (transport hubs, cash
# points, fuel, schools, retail). PLACES only — never people. Cost scales
# linearly with this list (~max_places billed results per term per area, at
# roughly $0.002/place), so additions must earn their keep.
POI_SEARCH_TERMS = [
    "police station",
    "hospital",
    "fire station",
    "security company",   # armed response — often the fastest responder in SA
    "school",
    "shopping centre",
    "gas station",
    "bank",
    "taxi rank",
    "bus station",
]


def run_poi_for_area(
    area: str,
    store: Optional[DataEngineStore] = None,
    client: Optional[ApifyClient] = None,
    max_places: int = 20,
    now: Optional[datetime] = None,
) -> IngestResult:
    """Ingest security-relevant points of interest for one area.

    Searches for the categories an analyst actually cares about — emergency
    response and the places that shape an area's activity — not people.

    The area goes in `locationQuery` (the actor geocodes it and searches AROUND
    that point), NOT inside the search strings. Observed live 2026-07-15:
    "police station Somerset West" keyword-matched station NAMES worldwide and
    returned St. Louis / New Jersey / Utah results — billed junk. Generic terms
    anchored to a geocoded location stay local.
    """
    if not area:
        return IngestResult(source_id="places.poi", error="no area given")

    return run_source(
        "places.poi",
        store=store,
        client=client,
        now=now,
        input_overrides={
            "searchStringsArray": list(POI_SEARCH_TERMS),
            "locationQuery": area,
            "maxCrawledPlacesPerSearch": max_places,
        },
        # Google's `city` is often the metro, not the suburb the camera is in —
        # stamp the area we queried so context/freshness can match it back.
        payload_extra={"query_area": area},
    )
