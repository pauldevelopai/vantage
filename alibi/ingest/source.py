"""
What a source is, and what it must declare before it may run.

The pipeline's job is to bring in a great deal of material cheaply. That makes
it exactly the component where an unlawful import becomes easy and invisible,
so provenance is not metadata attached afterwards — it is the precondition.

A Source without a declared lawful BASIS and a named authoriser cannot be
constructed. There is no "unknown" default and no bypass flag, because the
moment one exists it becomes the path of least resistance at 2am.

Every record the pipeline emits carries the source that produced it, so any
item can be traced back to what permitted it — and removed if that permission
ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, Optional, Protocol, runtime_checkable


class ProvenanceError(ValueError):
    """A source tried to run without a lawful basis for its material."""


# The bases this deployment recognises. Deliberately short and concrete: a free
# text field would be filled with "internal use" and mean nothing.
BASES = {
    "own_cameras":     "Recorded by cameras this deployment owns",
    "licensed":        "A dataset licensed for this use — licence must be named",
    "public_domain":   "Out of copyright or explicitly dedicated to the public domain",
    "owner_supplied":  "Provided by the owner from their own material",
    "consented":       "The people in it gave informed consent, and it is recorded",
}

# Bases that may contain identifiable people. Everything else must declare
# contains_people=False, and the pipeline enforces it.
PEOPLE_PERMITTED = {"own_cameras", "owner_supplied", "consented"}


@dataclass(frozen=True)
class Source:
    """A configured place material comes from."""
    source_id: str
    connector: str                 # which connector reads it
    config: Dict[str, Any] = field(default_factory=dict)

    # --- provenance: all required ---------------------------------------
    basis: str = ""                # one of BASES
    authorised_by: str = ""        # a person, by name. not "system".
    licence: str = ""              # required when basis == "licensed"
    contains_people: bool = False
    notes: str = ""
    added_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self) -> None:
        if self.basis not in BASES:
            raise ProvenanceError(
                f"source {self.source_id!r}: basis must be one of {sorted(BASES)}, "
                f"got {self.basis!r}. A source with no lawful basis cannot run.")
        if not self.authorised_by.strip():
            raise ProvenanceError(
                f"source {self.source_id!r}: authorised_by must name a person who "
                f"takes responsibility for this import.")
        if self.basis == "licensed" and not self.licence.strip():
            raise ProvenanceError(
                f"source {self.source_id!r}: basis 'licensed' requires the licence "
                f"to be named, so it can be checked and honoured.")
        if self.contains_people and self.basis not in PEOPLE_PERMITTED:
            raise ProvenanceError(
                f"source {self.source_id!r}: material containing identifiable "
                f"people cannot be imported under basis {self.basis!r}. "
                f"Permitted: {sorted(PEOPLE_PERMITTED)}.")

    def stamp(self) -> Dict[str, Any]:
        """What every record from this source carries, so it can be traced."""
        return {"source_id": self.source_id, "basis": self.basis,
                "licence": self.licence or None,
                "authorised_by": self.authorised_by,
                "contains_people": self.contains_people}


@dataclass
class Item:
    """One thing a connector produced."""
    external_id: str               # stable id within the source
    kind: str                      # "image" | "frame" | "metadata"
    content: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    captured_at: Optional[str] = None


@runtime_checkable
class Connector(Protocol):
    """Read a source. That is the whole contract.

    A connector does NOT deduplicate, embed, index or record provenance — the
    core does all of that identically for every source. Adding a new kind of
    source therefore means writing one method, and cannot change how the
    guarantees are enforced.
    """

    name: str

    def fetch(self, source: Source, since: Optional[str] = None) -> Iterator[Item]:
        ...
