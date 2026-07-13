"""
IntelligenceContextProvider - prior operator-recorded context for this area.

Surfaces unresolved red flags and elevated-risk place tags from the intelligence
store that relate to the incident's camera/zone. This is human-authored history,
so it is high-value context for the advisor. A matching high/critical unresolved
flag adds caution and forces review.
"""

from typing import List, Optional

from alibi.schemas import Incident
from alibi.config import AlibiConfig
from alibi.intelligence_store import get_intelligence_store
from alibi.context.schemas import Availability, ContextItem
from alibi.context.provider import ContextProvider
from alibi.context.providers._incident_signals import latest_camera_and_ts, location_hint

_ELEVATED = {"high", "critical"}


def _matches_location(free_text: Optional[str], hint: str) -> bool:
    if not hint:
        return False
    if not free_text:
        return False
    ft = free_text.lower()
    return any(tok and tok in ft for tok in hint.split())


class IntelligenceContextProvider(ContextProvider):
    name = "intelligence_store"

    def fetch(self, incident: Incident, config: Optional[AlibiConfig] = None) -> List[ContextItem]:
        camera_id, zone_id, _ts = latest_camera_and_ts(incident)
        hint = location_hint(camera_id, zone_id)
        store = get_intelligence_store()

        open_flags = store.get_red_flags(resolved=False, limit=100)
        # Flags whose free-text location loosely matches this camera/zone.
        local_flags = [f for f in open_flags if _matches_location(f.location, hint)]
        elevated_local = [f for f in local_flags if f.severity in _ELEVATED]

        high_risk_places = store.get_place_tags(risk_level="high", limit=100)
        local_places = [p for p in high_risk_places if _matches_location(p.name, hint) or _matches_location(p.description, hint)]

        if not local_flags and not local_places:
            return [ContextItem(
                provider=self.name, label="Prior intelligence",
                availability=Availability.ABSENT,
                source="intelligence store",
                metadata={"open_flags_total": len(open_flags)},
            )]

        parts = []
        if local_flags:
            parts.append(f"{len(local_flags)} unresolved red flag(s) recorded for this area")
        if local_places:
            names = ", ".join(sorted({p.name for p in local_places})[:3])
            parts.append(f"flagged high-risk location(s): {names}")

        caution_signals = []
        elevate = False
        if elevated_local:
            caution_signals.append("prior_high_risk_flag_this_area")
            elevate = True
        if local_places:
            caution_signals.append("high_risk_location")
            elevate = True

        return [ContextItem(
            provider=self.name, label="Prior intelligence",
            availability=Availability.PRESENT,
            summary=(". ".join(parts) + ". Recorded by operators; may be relevant background."),
            source="intelligence store",
            caution_signals=caution_signals,
            elevate_review=elevate,
            metadata={
                "local_flag_ids": [f.flag_id for f in local_flags][:20],
                "elevated_flag_ids": [f.flag_id for f in elevated_local][:20],
                "place_tag_ids": [p.place_tag_id for p in local_places][:20],
            },
        )]
