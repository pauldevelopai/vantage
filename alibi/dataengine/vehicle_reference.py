"""
Consumption of reference.vehicle_models: validate VLM-claimed vehicle badges.

The display rule is "a wrong make in front of a client is worse than no make".
The catalog gives that rule teeth: a claimed make that matches nothing we know
to be on the road here is downgraded to low confidence (the UI then shows
"White SUV", not the doubtful badge). The claim itself is kept as evidence —
we downgrade, never rewrite.
"""

import time
from typing import Any, Dict, List, Optional, Set

_cache: Dict[str, Any] = {"makes": None, "at": 0.0}
_TTL = 300.0


def known_makes(store=None) -> Set[str]:
    """Lower-cased makes from the reference catalog, cached briefly. Empty set
    when the catalog has no records — validation then changes nothing."""
    now = time.monotonic()
    if _cache["makes"] is not None and now - _cache["at"] < _TTL:
        return _cache["makes"]
    makes: Set[str] = set()
    try:
        if store is None:
            from alibi.dataengine.store import DataEngineStore
            store = DataEngineStore()
        for r in store.query(source_id="reference.vehicle_models"):
            m = (r.payload or {}).get("make")
            if m:
                makes.add(str(m).strip().lower())
    except Exception:
        makes = set()
    _cache["makes"] = makes
    _cache["at"] = now
    return makes


def validate_vehicle_attrs(vehicles: Optional[List[Dict[str, Any]]],
                           makes: Optional[Set[str]] = None) -> Optional[List[Dict[str, Any]]]:
    """Downgrade any claimed make not in the catalog to low confidence. Pure
    when `makes` is passed. An empty catalog validates nothing (no data ->
    no judgement)."""
    if not vehicles:
        return vehicles
    if makes is None:
        makes = known_makes()
    if not makes:
        return vehicles
    out = []
    for v in vehicles:
        v = dict(v)
        make = (v.get("make") or "").strip().lower()
        if make and make not in makes and v.get("confidence") == "high":
            v["confidence"] = "low"
            v["downgraded"] = "make not in reference catalog"
        out.append(v)
    return out
