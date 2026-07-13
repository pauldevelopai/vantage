"""
ContextProvider interface.

A provider turns an incident into zero or more ContextItems using ONE data
source (a learned baseline, the intelligence store, an access-log file, a
weather API, ...). Providers must be fail-safe: raising is acceptable (the
builder converts an exception into a single UNAVAILABLE item), but returning
fabricated data is NOT. If a source cannot be reached, return an UNAVAILABLE
item or raise — never invent an "all clear".
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from alibi.schemas import Incident
from alibi.config import VantageConfig
from alibi.context.schemas import ContextItem


class ContextProvider(ABC):
    """Base class for all context sources."""

    #: stable machine name, surfaced in provenance and audit logs
    name: str = "context_provider"

    @abstractmethod
    def fetch(self, incident: Incident, config: Optional[VantageConfig] = None) -> List[ContextItem]:
        """Return context items for this incident. May raise (handled by builder)."""
        raise NotImplementedError
