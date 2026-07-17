"""
Curated reference seeds for the data engine.

Not scraped and not guessed: these are published, publicly documented format
rules (the kind printed on licensing authority pages), hand-curated with a
source URL on every record and ingested through the SAME normalise → guard →
tag → store pipeline as any Apify feed — so provenance, lawful basis and
retention are identical to harvested data. Consumed by plate-OCR validation
(`reference.plate_formats`): a read that matches a known format gains
confidence; one that matches nothing is worth a second look.

Run on the box:  python -m alibi.dataengine.reference_seed
"""

from typing import Any, Dict, List

WIKI_ZA = "https://en.wikipedia.org/wiki/Vehicle_registration_plates_of_South_Africa"
WIKI_NA = "https://en.wikipedia.org/wiki/Vehicle_registration_plates_of_Namibia"

PLATE_FORMATS: List[Dict[str, Any]] = [
    {"region": "Gauteng", "country": "ZA", "pattern": r"^[A-Z]{2,3}\s?\d{2,3}\s?GP$",
     "example": "BX 42 GP",
     "description": "Gauteng: two/three letters, two/three digits, GP suffix.",
     "source_url": WIKI_ZA},
    {"region": "Western Cape", "country": "ZA", "pattern": r"^C[A-Z]{1,2}\s?\d{1,6}$",
     "example": "CA 123456",
     "description": "Western Cape town-coded: C + town letter(s) + up to six digits (CA Cape Town, CY Bellville, CL Stellenbosch).",
     "source_url": WIKI_ZA},
    {"region": "KwaZulu-Natal", "country": "ZA", "pattern": r"^N[A-Z]{1,2}\s?\d{1,6}$",
     "example": "ND 123456",
     "description": "KwaZulu-Natal town-coded: N + town letter(s) + digits (ND Durban, NP Pietermaritzburg).",
     "source_url": WIKI_ZA},
    {"region": "Mpumalanga", "country": "ZA", "pattern": r"^[A-Z]{3}\s?\d{3}\s?MP$",
     "example": "DSC 123 MP",
     "description": "Mpumalanga: three letters, three digits, MP suffix.",
     "source_url": WIKI_ZA},
    {"region": "Limpopo", "country": "ZA", "pattern": r"^[A-Z]{3}\s?\d{3}\s?L$",
     "example": "BBB 123 L",
     "description": "Limpopo: three letters, three digits, L suffix.",
     "source_url": WIKI_ZA},
    {"region": "North West", "country": "ZA", "pattern": r"^[A-Z]{3}\s?\d{3}\s?NW$",
     "example": "DDD 123 NW",
     "description": "North West: three letters, three digits, NW suffix.",
     "source_url": WIKI_ZA},
    {"region": "Free State", "country": "ZA", "pattern": r"^[A-Z]{3}\s?\d{3}\s?FS$",
     "example": "ABC 123 FS",
     "description": "Free State: three letters, three digits, FS suffix.",
     "source_url": WIKI_ZA},
    {"region": "Northern Cape", "country": "ZA", "pattern": r"^[A-Z]{3}\s?\d{3}\s?NC$",
     "example": "ABC 123 NC",
     "description": "Northern Cape: three letters, three digits, NC suffix.",
     "source_url": WIKI_ZA},
    {"region": "Eastern Cape", "country": "ZA", "pattern": r"^[A-Z]{3}\s?\d{3}\s?EC$",
     "example": "ABC 123 EC",
     "description": "Eastern Cape: three letters, three digits, EC suffix.",
     "source_url": WIKI_ZA},
    {"region": "Namibia", "country": "NA", "pattern": r"^N\s?\d{1,6}\s?[A-Z]{1,2}$",
     "example": "N 12345 W",
     "description": "Namibia town-coded: N + up to six digits + town letter(s) (W Windhoek, S Swakopmund, SH Windhoek area).",
     "source_url": WIKI_NA},
]


def seed_plate_formats(store=None, now=None):
    """Ingest the curated plate formats through the full pipeline. Idempotent —
    content-hash ids mean re-runs don't duplicate."""
    from alibi.dataengine.ingest import ingest_items
    from alibi.dataengine.sources import get_source
    from alibi.dataengine.store import DataEngineStore
    spec = get_source("reference.plate_formats")
    store = store or DataEngineStore()
    return ingest_items(spec, PLATE_FORMATS, store, now=now,
                        payload_extra={"provenance": "curated:published-format-documentation"})


def main() -> int:
    result = seed_plate_formats()
    print(f"plate formats: fetched={result.fetched} stored={result.stored} "
          f"skipped={result.skipped} rejected={result.rejected_personal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
