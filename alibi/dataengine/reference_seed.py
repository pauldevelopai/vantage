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
    r1 = seed_plate_formats()
    print(f"plate formats: fetched={r1.fetched} stored={r1.stored} "
          f"skipped={r1.skipped} rejected={r1.rejected_personal}")
    r2 = seed_vehicle_models()
    print(f"vehicle models: fetched={r2.fetched} stored={r2.stored} "
          f"skipped={r2.skipped} rejected={r2.rejected_personal}")
    return 0



# ── Vehicle make/model catalog (SA market) ─────────────────────────────────
# Curated from manufacturers' public model catalogues / NAAMSA market lists.
# Used to VALIDATE VLM-claimed makes and models — a claimed badge that matches
# nothing in the catalog is downgraded, never displayed.

NAAMSA = "https://naamsa.net/sa-auto-industry/vehicle-sales/"

_SA_VEHICLES = [
    ("Toyota", ["Hilux", "Fortuner", "Corolla", "Corolla Cross", "Starlet", "Urban Cruiser", "Land Cruiser", "RAV4", "Quantum", "Vitz", "Rumion", "Prado"]),
    ("Volkswagen", ["Polo", "Polo Vivo", "T-Cross", "Tiguan", "Golf", "Amarok", "T-Roc", "Caddy", "Transporter"]),
    ("Ford", ["Ranger", "Everest", "EcoSport", "Figo", "Territory", "Transit"]),
    ("Nissan", ["NP200", "Navara", "Magnite", "X-Trail", "Qashqai", "Almera", "Patrol"]),
    ("Hyundai", ["i10", "i20", "Venue", "Creta", "Tucson", "H-100", "Staria", "Santa Fe"]),
    ("Kia", ["Picanto", "Sonet", "Seltos", "Sportage", "Rio", "Pegas"]),
    ("Suzuki", ["Swift", "S-Presso", "Baleno", "Jimny", "Fronx", "Ertiga", "Vitara Brezza", "Grand Vitara"]),
    ("Isuzu", ["D-Max", "MU-X"]),
    ("Renault", ["Kwid", "Triber", "Kiger", "Duster", "Clio"]),
    ("Haval", ["Jolion", "H6"]),
    ("GWM", ["P-Series", "Steed"]),
    ("Mahindra", ["Pik Up", "Scorpio", "XUV300", "XUV700"]),
    ("BMW", ["1 Series", "3 Series", "X1", "X3", "X5"]),
    ("Mercedes-Benz", ["A-Class", "C-Class", "GLA", "GLC", "Vito", "Sprinter"]),
    ("Audi", ["A3", "A4", "Q2", "Q3", "Q5"]),
    ("Chery", ["Tiggo 4 Pro", "Tiggo 7 Pro", "Tiggo 8 Pro", "Omoda C5"]),
    ("Omoda", ["C5", "C9"]),
    ("Mazda", ["CX-3", "CX-30", "CX-5", "Mazda2", "Mazda3", "BT-50"]),
    ("Honda", ["Fit", "Ballade", "BR-V", "HR-V", "CR-V"]),
    ("Mitsubishi", ["Triton", "Pajero Sport", "ASX", "Xpander"]),
    ("Land Rover", ["Defender", "Discovery", "Range Rover Evoque"]),
    ("Peugeot", ["208", "2008", "3008", "Landtrek"]),
    ("Opel", ["Corsa", "Crossland", "Grandland"]),
    ("Fiat", ["500", "Tipo"]),
    ("Jeep", ["Wrangler", "Grand Cherokee", "Compass"]),
]

VEHICLE_MODELS = [
    {"make": make, "model": model, "source_url": NAAMSA}
    for make, models in _SA_VEHICLES
    for model in models
]


def seed_vehicle_models(store=None, now=None):
    """Ingest the curated SA vehicle catalog through the full pipeline."""
    from alibi.dataengine.ingest import ingest_items
    from alibi.dataengine.sources import get_source
    from alibi.dataengine.store import DataEngineStore
    spec = get_source("reference.vehicle_models")
    store = store or DataEngineStore()
    return ingest_items(spec, VEHICLE_MODELS, store, now=now,
                        payload_extra={"provenance": "curated:manufacturer-catalogues"})


if __name__ == "__main__":
    raise SystemExit(main())
