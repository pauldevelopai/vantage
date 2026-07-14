"""
Vantage Data Engine — source registry (§9).

Each source DECLARES its domain, lawful basis and retention up front — you
cannot register one without them (see SourceSpec).

Normalisers are ALLOWLIST-based: they copy only the fields they declare and drop
everything else. That means an upstream actor which suddenly starts emitting
personal fields loses them at normalisation, before the guard is even reached.
Defence in depth: allowlist (here) -> guard (guard.py) -> tagged store (store.py).
"""

from typing import Any, Dict, List, Optional

from alibi.dataengine.schemas import DataDomain, LawfulBasis, SourceSpec


def _pick(item: Dict[str, Any], allowed: List[str]) -> Dict[str, Any]:
    """Copy ONLY the allowed keys. Everything else is discarded."""
    return {k: item[k] for k in allowed if k in item and item[k] is not None}


# --------------------------------------------------------------------------- #
# Places / context (non-personal) — feeds "why flagged" context + Security Advisor
# --------------------------------------------------------------------------- #

AREA_CRIME_STATS_FIELDS = [
    "area", "province", "period", "crime_category", "count", "rate_per_100k",
    "latitude", "longitude", "source_url",
]


def normalise_area_crime_stats(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = _pick(item, AREA_CRIME_STATS_FIELDS)
    # Require the fields that make the record meaningful — else skip it (no
    # half-empty rows; honest data only).
    if not payload.get("area") or payload.get("count") is None:
        return None
    return payload


POI_FIELDS = [
    "place_name", "category", "latitude", "longitude", "address",
    "opening_hours", "source_url",
]


def normalise_poi(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Points of interest — police stations, hospitals, businesses, landmarks.

    `place_name`/`address` describe a PLACE, not a person (see guard.py).
    """
    payload = _pick(item, POI_FIELDS)
    if not payload.get("place_name"):
        return None
    return payload


# --------------------------------------------------------------------------- #
# Detection reference — improves plates (§3) and make/model (§3)
# --------------------------------------------------------------------------- #

VEHICLE_MODEL_FIELDS = [
    "make", "model", "year_from", "year_to", "body_type", "common_colors",
    "source_url",
]


def normalise_vehicle_model(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = _pick(item, VEHICLE_MODEL_FIELDS)
    if not payload.get("make") or not payload.get("model"):
        return None
    return payload


PLATE_FORMAT_FIELDS = [
    "region", "country", "pattern", "example", "description", "source_url",
]


def normalise_plate_format(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = _pick(item, PLATE_FORMAT_FIELDS)
    if not payload.get("pattern"):
        return None
    return payload


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

SOURCES: Dict[str, SourceSpec] = {}


def register(spec: SourceSpec) -> SourceSpec:
    SOURCES[spec.source_id] = spec
    return spec


def get_source(source_id: str) -> Optional[SourceSpec]:
    return SOURCES.get(source_id)


def list_sources(domain: Optional[DataDomain] = None) -> List[SourceSpec]:
    specs = list(SOURCES.values())
    if domain:
        specs = [s for s in specs if s.domain == domain]
    return sorted(specs, key=lambda s: s.source_id)


# Built-in source declarations. `apify_actor` / `actor_input` are filled in when
# a real actor is wired; the engine runs against any actor that yields items of
# the declared shape.
register(SourceSpec(
    source_id="places.area_crime_stats",
    domain=DataDomain.PLACES_CONTEXT,
    lawful_basis=LawfulBasis.PUBLIC_INTEREST_STATISTICS,
    retention_days=365,
    description="Published area crime statistics (non-personal, aggregate).",
    normaliser=normalise_area_crime_stats,
))

register(SourceSpec(
    source_id="places.poi",
    domain=DataDomain.PLACES_CONTEXT,
    lawful_basis=LawfulBasis.LEGITIMATE_INTEREST_NON_PERSONAL,
    retention_days=180,
    description="Points of interest — police stations, hospitals, businesses, landmarks.",
    normaliser=normalise_poi,
))

register(SourceSpec(
    source_id="reference.vehicle_models",
    domain=DataDomain.DETECTION_REFERENCE,
    lawful_basis=LawfulBasis.PUBLICLY_AVAILABLE_REFERENCE,
    retention_days=365,
    description="Vehicle make/model catalog — improves make/model detection.",
    normaliser=normalise_vehicle_model,
))

register(SourceSpec(
    source_id="reference.plate_formats",
    domain=DataDomain.DETECTION_REFERENCE,
    lawful_basis=LawfulBasis.PUBLICLY_AVAILABLE_REFERENCE,
    retention_days=365,
    description="Number-plate format rules by region — improves plate OCR validation.",
    normaliser=normalise_plate_format,
))
