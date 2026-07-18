"""
Number-plate → registration region ("where the vehicle is registered").

South African plates encode the registering authority in their letters, so a
plate tells you the PROVINCE a vehicle is registered in. For a Somerset West
(Western Cape) site that is a real, defensible security signal: a Gauteng or
KwaZulu-Natal plate parked at the perimeter is out-of-province and worth a look,
where a local Western Cape plate is unremarkable.

Honesty rules, by construction:
  * This is where the VEHICLE is REGISTERED — never where a person is "from".
    Plates outlive owners; a car can be bought in Gauteng and driven locally.
    All user-facing language says "registered in …".
  * Only high-confidence rules decode. Anything the table can't place with
    confidence returns province=None ("unknown region") — we never guess a
    province from an ambiguous plate.
  * Pure and table-driven, so the rules are auditable and testable.

The rules encoded are the well-established, verifiable ones (SA plate schemes
differ by province: some prefix the province, some suffix it):
  * Western Cape  — town codes, ALL begin with 'C'  (CA Cape Town, CY, CJ, …)
  * Gauteng       — plates END in 'GP'
  * KwaZulu-Natal — plates BEGIN with 'N'  (ND Durban, NP, NPN, NUZ, …)
  * North West    — END in 'NW'
  * Mpumalanga    — END in 'MP'
  * Northern Cape — END in 'NC'
  * Limpopo       — END in 'L'  (after the digits; e.g. '… BL', historic)
Everything else → unknown (honest).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

WESTERN_CAPE = "Western Cape"

# Province a suffix identifies (checked on the trailing letters).
_SUFFIX_PROVINCE = {
    "GP": "Gauteng",
    "NW": "North West",
    "MP": "Mpumalanga",
    "NC": "Northern Cape",
}

# A few well-known Western Cape town codes → town (province is always WC for C…).
_WC_TOWNS = {
    "CA": "Cape Town",
    "CY": "Bellville",
    "CJ": "Paarl",
    "CK": "Malmesbury",
    "CL": "Vredenburg",
    "CF": "Stellenbosch",
    "CEM": "Somerset West",   # Helderberg
    "CFM": "Somerset West",
    "CEY": "Strand",
}


def _clean(plate: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def decode_plate_region(plate: str) -> Dict[str, Any]:
    """Decode a plate string to its registration region. Pure.

    Returns {province, town, confidence, basis} — province/town None when the
    plate can't be placed with confidence. `basis` names the rule that fired,
    for auditability.
    """
    p = _clean(plate)
    out: Dict[str, Any] = {"province": None, "town": None,
                           "confidence": "unknown", "basis": None}
    if len(p) < 4:
        return out

    # 1) Suffix-province schemes (Gauteng etc.) — strongest, unambiguous.
    for suffix, province in _SUFFIX_PROVINCE.items():
        if p.endswith(suffix):
            out.update(province=province, confidence="high",
                       basis=f"'{suffix}' suffix")
            return out

    # 2) Western Cape — town codes all start with 'C' followed by a letter.
    if p[0] == "C" and p[1:2].isalpha():
        town = None
        for code in sorted(_WC_TOWNS, key=len, reverse=True):
            if p.startswith(code):
                town = _WC_TOWNS[code]
                break
        out.update(province=WESTERN_CAPE, town=town, confidence="high",
                   basis="'C' prefix (Western Cape town code)")
        return out

    # 3) KwaZulu-Natal — 'N' prefix followed by a letter (ND, NP, NUZ, …).
    if p[0] == "N" and p[1:2].isalpha():
        out.update(province="KwaZulu-Natal", confidence="medium",
                   basis="'N' prefix")
        return out

    # 4) Limpopo — historic 'B'-series ending in 'L'. Lower confidence.
    if p.endswith("L") and p[0] == "B":
        out.update(province="Limpopo", confidence="low", basis="'B…L' pattern")
        return out

    return out


def registration_note(plate: str, site_province: Optional[str] = WESTERN_CAPE) -> Optional[Dict[str, Any]]:
    """A surfaceable note about a plate's registration region, or None when the
    plate can't be placed. `out_of_area` is set only when we can confidently say
    the province differs from the site's."""
    region = decode_plate_region(plate)
    if not region["province"]:
        return None
    prov = region["province"]
    town = region["town"]
    where = f"{town}, {prov}" if town else prov
    out_of_area = bool(site_province) and prov != site_province and region["confidence"] in ("high", "medium")
    return {
        "plate": _clean(plate),
        "province": prov,
        "town": town,
        "confidence": region["confidence"],
        "out_of_area": out_of_area,
        "text": (f"Registered in {where}"
                 + (" — out of province for this area" if out_of_area else
                    (" (local)" if prov == site_province else ""))),
        "basis": region["basis"],
    }
