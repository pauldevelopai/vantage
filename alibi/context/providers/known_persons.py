"""
KnownPersonsContextProvider - was a known person matched upstream?

If upstream appearance/ReID attached a known-person id to the incident, surface
that person's trust level. Caution-only semantics:
  - a "trusted" or "neutral" authorized match is INFORMATIONAL ONLY. We never use
    it to lower severity or downgrade review (context can't de-escalate).
  - a "watch" match adds caution and forces review.
If no match was performed, the item is ABSENT (honest) - not "nobody known here".
"""

from typing import List, Optional

from alibi.schemas import Incident
from alibi.config import AlibiConfig
from alibi.known_persons import get_known_persons_store
from alibi.context.schemas import Availability, ContextItem
from alibi.context.provider import ContextProvider

_MATCH_KEYS = ("known_person_id", "matched_person_id", "person_id")


def _find_match_id(incident: Incident) -> Optional[str]:
    for key in _MATCH_KEYS:
        val = (incident.metadata or {}).get(key)
        if val:
            return str(val)
    for e in incident.events:
        for key in _MATCH_KEYS:
            val = (e.metadata or {}).get(key)
            if val:
                return str(val)
    return None


class KnownPersonsContextProvider(ContextProvider):
    name = "known_persons"

    def fetch(self, incident: Incident, config: Optional[AlibiConfig] = None) -> List[ContextItem]:
        match_id = _find_match_id(incident)
        if not match_id:
            return [ContextItem(
                provider=self.name, label="Known-person match",
                availability=Availability.ABSENT,
                source="known persons store",
                metadata={"reason": "no upstream known-person match on incident"},
            )]

        store = get_known_persons_store()
        person = store.get_person(match_id)
        if person is None:
            # We have an id but the record is gone - report honestly, don't guess.
            return [ContextItem(
                provider=self.name, label="Known-person match",
                availability=Availability.UNAVAILABLE,
                source="known persons store",
                metadata={"reason": f"matched id {match_id} not found in store"},
            )]

        trust = (person.trust_level or "neutral").lower()
        if trust == "watch" or not person.is_authorized:
            return [ContextItem(
                provider=self.name, label="Known-person match",
                availability=Availability.PRESENT,
                summary=(
                    f"Appearance may match a person on the watch list "
                    f"(role: {person.role}). Requires verification."
                ),
                source="known persons store",
                caution_signals=["known_person_on_watch"],
                elevate_review=True,
                metadata={"person_id": person.person_id, "trust_level": trust},
            )]

        # trusted / neutral & authorized -> informational only (never de-escalates)
        return [ContextItem(
            provider=self.name, label="Known-person match",
            availability=Availability.PRESENT,
            summary=(
                f"Appearance may match a known {trust} person (role: {person.role}). "
                f"Informational only - does not reduce required review."
            ),
            source="known persons store",
            metadata={"person_id": person.person_id, "trust_level": trust},
        )]
