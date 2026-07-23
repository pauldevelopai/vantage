"""
A make/model classifier that learns from YOUR confirmations. Nothing else.

The review queue had been collecting confirmed crops and calling itself "the
local-training corpus" while nothing trained on it — every judgement Paul made
was filed against a classifier that did not exist. This is that classifier.

What it learns from: vehicle crops from this deployment's own cameras, labelled
by the owner in the review queue. No scraped photographs, no public datasets,
no people — vehicles only, and only the ones that actually come to the
property.

How it works, and why not fine-tuning: the box is a 3.8GB CPU-only VM and the
corpus is tens of examples. Retraining a detector's weights on that would
overfit to those few clicks and make recognition worse. Instead each label
becomes a CENTROID in the appearance-embedding space the ReID stack already
produces, and a new crop is assigned to the nearest one if it is close enough.
That is the correct technique at this scale: it trains in seconds, needs no
GPU, and genuinely improves every time a label is confirmed.

It is OFF until switched on, and it never overrides what a vision model
actually read — it only offers a guess where there was none.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

MODEL_FILE = Path("alibi/data/vehicle_classifier.json")

# A label needs at least this many confirmed examples before it is worth
# offering. One photograph of one angle is not a class.
MIN_EXAMPLES_PER_LABEL = 3

# How close a crop must sit to a centroid before we name it. Deliberately
# high: a wrong make in front of a client is worse than no make at all.
MIN_CONFIDENCE = 0.65


def _state() -> dict:
    try:
        return json.loads(MODEL_FILE.read_text()) or {}
    except (FileNotFoundError, ValueError):
        return {}
    except Exception as e:  # pragma: no cover
        print(f"[vehicle-classifier] unreadable: {e}")
        return {}


def _save(state: dict) -> None:
    try:
        from alibi.atomic_json import write_json
        write_json(MODEL_FILE, state)
    except Exception as e:  # pragma: no cover
        print(f"[vehicle-classifier] could not save: {e}")


def set_enabled(on: bool) -> dict:
    state = _state()
    state["enabled"] = bool(on)
    _save(state)
    return status()


def is_enabled() -> bool:
    return bool(_state().get("enabled"))


def centroids_from(examples: List[Tuple[str, np.ndarray]]) -> Dict[str, list]:
    """Mean embedding per label, L2-normalised. Pure, so it is testable."""
    by_label: Dict[str, list] = {}
    for label, vec in examples:
        v = np.asarray(vec, dtype=np.float32).ravel()
        n = float(np.linalg.norm(v))
        if n:
            by_label.setdefault(label, []).append(v / n)

    out = {}
    for label, vecs in by_label.items():
        # Keep only the dominant dimension: a corpus embedded across an embedder
        # change holds mixed widths, and np.stack on ragged shapes raises and
        # takes the whole training run down. predict() already guards this way.
        from collections import Counter
        dims = Counter(v.shape[0] for v in vecs)
        keep = dims.most_common(1)[0][0]
        vecs = [v for v in vecs if v.shape[0] == keep]
        if len(vecs) < MIN_EXAMPLES_PER_LABEL:
            continue                      # not enough to be a class yet
        mean = np.mean(np.stack(vecs), axis=0)
        n = float(np.linalg.norm(mean))
        if n:
            out[label] = (mean / n).tolist()
    return out


def predict(embedding, min_confidence: float = MIN_CONFIDENCE) -> Optional[dict]:
    """Best matching label for this crop, or None.

    Returns None when switched off, untrained, or simply not sure — "no guess"
    is a valid and frequent answer.
    """
    if not is_enabled():
        return None
    state = _state()
    cents = state.get("centroids") or {}
    if not cents or embedding is None:
        return None

    v = np.asarray(embedding, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    if not n:
        return None
    v = v / n

    best, score = None, 0.0
    for label, c in cents.items():
        c = np.asarray(c, dtype=np.float32).ravel()
        if c.shape != v.shape:
            continue                      # embedder changed; ignore stale classes
        s = float(np.dot(v, c))
        if s > score:
            best, score = label, s
    if best is None or score < min_confidence:
        return None
    return {"label": best, "confidence": round(score, 3), "source": "local_classifier"}


def train(embed_crop) -> dict:
    """Rebuild from every confirmed label. `embed_crop(frame_url, bbox)` -> vec.

    Passed in rather than imported so this stays testable without the vision
    stack, and so the caller owns the cost of loading models.
    """
    from alibi.vehicles.review_queue import get_review_queue_store

    rows = get_review_queue_store().confirmed_labels()
    examples, skipped = [], 0
    for row in rows:
        try:
            vec = embed_crop(row.get("frame_url"), row.get("bbox"))
        except Exception:
            vec = None
        if vec is None:
            skipped += 1
            continue
        examples.append((str(row.get("label")).strip(), vec))

    cents = centroids_from(examples)
    state = _state()
    state.update({
        "centroids": cents,
        "labels": sorted(cents),
        "examples_used": len(examples),
        "examples_skipped": skipped,
        "confirmed_available": len(rows),
        "trained_at": datetime.utcnow().isoformat(),
    })
    _save(state)
    print(f"[vehicle-classifier] trained on {len(examples)} of {len(rows)} "
          f"confirmed crops -> {len(cents)} label(s)", flush=True)
    return status()


def status() -> dict:
    """What it knows, in terms a person can check."""
    s = _state()
    return {
        "enabled": bool(s.get("enabled")),
        "labels": s.get("labels") or [],
        "label_count": len(s.get("labels") or []),
        "examples_used": s.get("examples_used", 0),
        "examples_skipped": s.get("examples_skipped", 0),
        "confirmed_available": s.get("confirmed_available", 0),
        "trained_at": s.get("trained_at"),
        "min_examples_per_label": MIN_EXAMPLES_PER_LABEL,
        "min_confidence": MIN_CONFIDENCE,
        "trained_on": "your own confirmed crops only — no scraped data, no people",
    }
