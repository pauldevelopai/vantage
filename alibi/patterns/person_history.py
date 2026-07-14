"""
Person History — "have these people been involved before?"

Given a face embedding (ArcFace, from Phase 1), search the face-sighting
archive for prior appearances and summarise them: how often, at which cameras,
over what span, and whether any prior sighting matched the police watchlist.

Human-in-the-loop / No-Accuse: this SURFACES prior sightings for an operator to
review. It never asserts identity or guilt — language stays "possible".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Any

import numpy as np

from alibi.watchlist.face_sighting_store import get_face_sighting_store, FaceSighting


@dataclass
class PriorSighting:
    camera_id: str
    ts: str                       # ISO timestamp
    score: float                  # cosine similarity to the query face
    matched_person_id: Optional[str] = None


@dataclass
class PersonHistoryResult:
    seen_before: bool
    times_seen: int
    distinct_cameras: List[str]
    first_seen: Optional[str]
    last_seen: Optional[str]
    watchlist_person_id: Optional[str]     # set if any prior sighting matched the watchlist
    prior_sightings: List[PriorSighting] = field(default_factory=list)
    summary: str = ""


class PersonHistory:
    """
    Looks a detected face up against the face-sighting archive.

    Wraps FaceSightingStore.find_similar (cosine search over stored ArcFace
    embeddings). Threshold defaults are conservative — better to under-report a
    prior appearance than to falsely link two different people.
    """

    def __init__(self, match_threshold: float = 0.5, limit: int = 200, store=None):
        self.match_threshold = match_threshold
        self.limit = limit
        self.store = store if store is not None else get_face_sighting_store()

    def look_up(
        self,
        embedding: Any,
        exclude_sighting_id: Optional[str] = None,
    ) -> PersonHistoryResult:
        """
        Find prior sightings of the person in `embedding`.

        Args:
            embedding: query face embedding (ArcFace, any dim — must match the
                stored embeddings' dim; mismatched entries are skipped).
            exclude_sighting_id: the current detection's own sighting id, so the
                just-recorded frame isn't reported as its own "prior".
        """
        emb = np.asarray(embedding, dtype=np.float32).ravel()
        matches = self.store.find_similar(emb, threshold=self.match_threshold, limit=self.limit)

        priors: List[PriorSighting] = []
        for sighting, score in matches:
            if exclude_sighting_id and sighting.sighting_id == exclude_sighting_id:
                continue
            priors.append(PriorSighting(
                camera_id=sighting.camera_id,
                ts=sighting.ts,
                score=round(float(score), 4),
                matched_person_id=sighting.matched_person_id,
            ))

        if not priors:
            return PersonHistoryResult(
                seen_before=False, times_seen=0, distinct_cameras=[],
                first_seen=None, last_seen=None, watchlist_person_id=None,
                prior_sightings=[], summary="No prior appearances found in the archive.",
            )

        cameras = sorted({p.camera_id for p in priors})
        timestamps = sorted(p.ts for p in priors)
        watchlist_id = next((p.matched_person_id for p in priors if p.matched_person_id), None)

        summary = self._summarise(len(priors), cameras, timestamps[0], timestamps[-1], watchlist_id)

        return PersonHistoryResult(
            seen_before=True,
            times_seen=len(priors),
            distinct_cameras=cameras,
            first_seen=timestamps[0],
            last_seen=timestamps[-1],
            watchlist_person_id=watchlist_id,
            prior_sightings=priors,
            summary=summary,
        )

    @staticmethod
    def _summarise(count, cameras, first, last, watchlist_id) -> str:
        cam_word = "camera" if len(cameras) == 1 else "cameras"
        span = f"since {first[:10]}" if first == last else f"between {first[:10]} and {last[:10]}"
        base = (f"Possible prior appearances: seen {count} time(s) across "
                f"{len(cameras)} {cam_word} {span}.")
        if watchlist_id:
            base += f" A prior sighting matched watchlist person '{watchlist_id}' — operator review required."
        return base
