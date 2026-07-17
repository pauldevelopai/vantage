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
    # The evidence behind the row — so history renders as face crops a human
    # can actually check, not anonymous text lines.
    sighting_id: Optional[str] = None
    frame_url: Optional[str] = None
    bbox: Optional[List[int]] = None


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
                sighting_id=sighting.sighting_id,
                frame_url=sighting.image_path,
                bbox=list(sighting.bbox) if sighting.bbox else None,
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


def recent_people(
    cutoff_iso: str,
    max_rows: int = 12,
    match_threshold: float = 0.5,
    store=None,
    labels: Optional[dict] = None,
    watchlist_embeddings: Optional[dict] = None,
    watchlist_threshold: float = 0.6,
) -> List[dict]:
    """The Overview's people strip: recent distinct faces, each with its evidence
    frame + bbox (for a client-side crop), who it is — honestly — and continuity.

    The boundary, enforced here: an ENROLLED person (matched_person_id set by the
    conservative watchlist match, or a read-time match against the owner's own
    enrolled embeddings, same conservative threshold) gets their real label. A
    stranger gets continuity only — times seen / first seen from a cosine search
    over OUR OWN sighting archive. We never guess who an unknown person is.

    The read-time watchlist match is what makes enrolment compound immediately:
    enrol a face and the strip's existing tiles of that person say the name on
    the next load, not just future sightings.

    Cost is bounded: the archive is loaded ONCE and embedded into one matrix; each
    of the ≤max_rows picked faces is one vector·matrix product (no per-row store
    reload, no N×N work). Rows without a stored evidence frame are skipped — a
    tile we can't show a real face shot for is not shown at all.
    """
    store = store if store is not None else get_face_sighting_store()
    labels = labels or {}

    all_sightings = store.load_all()
    if not all_sightings:
        return []

    # One pass: normalised embedding matrix over the whole archive.
    embs, kept = [], []
    for s in all_sightings:
        e = np.asarray(s.embedding, dtype=np.float32).ravel()
        n = float(np.linalg.norm(e))
        if e.size == 0 or n == 0:
            continue
        embs.append(e / n)
        kept.append(s)
    if not kept:
        return []
    dim = embs[0].shape[0]
    same_dim = [i for i, e in enumerate(embs) if e.shape[0] == dim]
    matrix = np.stack([embs[i] for i in same_dim])
    kept = [kept[i] for i in same_dim]
    embs = [embs[i] for i in same_dim]

    def _usable(s) -> bool:
        # A tile needs a real evidence frame and a face big enough to be one —
        # a sub-16px "face" at 640px width is detector noise, not a person.
        if not (s.ts >= cutoff_iso and s.image_path and s.bbox):
            return False
        try:
            return int(s.bbox[2]) >= 16 and int(s.bbox[3]) >= 16
        except (TypeError, ValueError, IndexError):
            return False

    recent = sorted(
        (i for i, s in enumerate(kept) if _usable(s)),
        key=lambda i: kept[i].ts, reverse=True,
    )

    rows: List[dict] = []
    chosen: List[np.ndarray] = []
    for i in recent:
        if len(rows) >= max_rows:
            break
        s, e = kept[i], embs[i]
        # The same person shouldn't fill the strip — skip faces similar to one
        # already shown (a burst of frames of one visitor is one tile).
        if any(float(np.dot(e, c)) >= match_threshold for c in chosen):
            continue
        sims = matrix @ e
        alike = sims >= match_threshold          # includes this sighting itself
        times_seen = int(np.count_nonzero(alike))
        first_seen = min(kept[j].ts for j in np.flatnonzero(alike))
        # Enrolled -> the real label (stamped at detection time, or matched now
        # against the owner's enrolled embeddings at the same conservative
        # threshold). Stranger -> null; the row carries continuity instead.
        # Never an identity guess.
        matched_label = labels.get(s.matched_person_id) if s.matched_person_id else None
        if matched_label is None and watchlist_embeddings:
            best_pid, best = None, watchlist_threshold
            for pid, wemb in watchlist_embeddings.items():
                w = np.asarray(wemb, dtype=np.float32).ravel()
                n = float(np.linalg.norm(w))
                if n == 0 or w.shape[0] != e.shape[0]:
                    continue
                score = float(np.dot(e, w / n))
                if score >= best:
                    best_pid, best = pid, score
            if best_pid is not None:
                matched_label = labels.get(best_pid)
        rows.append({
            "sighting_id": s.sighting_id,
            "frame_url": s.image_path,
            "bbox": list(s.bbox),
            "camera_id": s.camera_id,
            "ts": s.ts,
            "matched_label": matched_label,
            "times_seen": times_seen,
            "first_seen": first_seen,
        })
        chosen.append(e)
    return rows
