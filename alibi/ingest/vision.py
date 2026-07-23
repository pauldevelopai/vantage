"""
Wire the ingestion core to the vision stack it already has.

The pipeline's `embed` and `index` are injected on purpose — the core stays
testable without models, and the same core can serve a text source. These are
the real implementations for images: decode the item, embed it with the SAME
ReID model the live camera path uses, and write the vector to a searchable
store that keeps the provenance stamp beside it.

Embedders are built ONCE and reused. Constructing an AppearanceEmbedder loads a
model; doing it per item would make a million-item run a million model loads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from alibi.ingest.source import Item, Source

VECTORS_FILE = Path("alibi/data/ingest_vectors.jsonl")

_embedders: Dict[str, Any] = {}


def _embedder(kind: str):
    """One embedder per kind, held for the life of the process."""
    if kind not in _embedders:
        from alibi.cameras.appearance_reid import AppearanceEmbedder
        _embedders[kind] = AppearanceEmbedder(kind=kind)
    return _embedders[kind]


def _decode(item: Item):
    """Item's JPEG/PNG bytes -> BGR frame, or None."""
    if not item.content:
        return None
    import cv2
    arr = np.frombuffer(item.content, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def make_embed(kind: str = "vehicle"):
    """An `embed(item)` for pipeline.ingest, using the live ReID model.

    A crop's bbox may ride in item.metadata['bbox']; otherwise the whole image
    is embedded. Returns None when there is no backend or nothing to embed —
    the pipeline handles that, indexing metadata-only.
    """
    def embed(item: Item):
        if item.kind not in ("image", "frame"):
            return None
        frame = _decode(item)
        if frame is None:
            return None
        bbox = item.metadata.get("bbox")
        if bbox and len(bbox) == 4:
            x, y, w, h = (int(v) for v in bbox)
            crop = frame[max(0, y):y + h, max(0, x):x + w]
            frame = crop if crop.size else frame
        emb = _embedder(kind).embed(frame)
        return None if emb is None else np.asarray(emb, dtype=np.float32)
    return embed


class VectorStore:
    """Append-only searchable index: one row per item, vector + provenance.

    JSONL and a linear scan — honest about scale. It is correct and traceable
    at tens of thousands, which is where this deployment is. A note in the
    status output says plainly when a real ANN index (faiss/hnsw) is warranted,
    rather than pretending this is that.
    """

    def __init__(self, path: Path = VECTORS_FILE):
        self.path = path
        self._rows: Optional[List[dict]] = None

    def _load(self) -> List[dict]:
        if self._rows is not None:
            return self._rows
        rows: List[dict] = []
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            continue
        except FileNotFoundError:
            pass
        self._rows = rows
        return rows

    def add(self, key: str, item: Item, source: Source, vector) -> None:
        row = {
            "key": key,
            "kind": item.kind,
            "external_id": item.external_id,
            "captured_at": item.captured_at,
            "vector": [float(x) for x in np.asarray(vector).ravel()] if vector is not None else None,
            "provenance": source.stamp(),
            "metadata": {k: v for k, v in item.metadata.items() if k != "bbox"},
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:  # pragma: no cover
            print(f"[ingest] could not index {key}: {e}", flush=True)
        if self._rows is not None:
            self._rows.append(row)

    def search(self, vector, limit: int = 20,
               min_score: float = 0.5) -> List[Tuple[dict, float]]:
        """Nearest indexed items to a query vector, best first."""
        q = np.asarray(vector, dtype=np.float32).ravel()
        n = float(np.linalg.norm(q))
        if not n:
            return []
        q = q / n
        out = []
        for row in self._load():
            v = row.get("vector")
            if not v:
                continue
            w = np.asarray(v, dtype=np.float32).ravel()
            if w.shape != q.shape:
                continue
            wn = float(np.linalg.norm(w))
            if not wn:
                continue
            score = float(np.dot(q, w / wn))
            if score >= min_score:
                out.append((row, round(score, 4)))
        out.sort(key=lambda r: r[1], reverse=True)
        return out[:limit]

    def stats(self) -> dict:
        rows = self._load()
        vecs = sum(1 for r in rows if r.get("vector"))
        return {
            "indexed": len(rows),
            "with_vectors": vecs,
            "metadata_only": len(rows) - vecs,
            "index_type": "linear-scan JSONL",
            "note": ("Exact and traceable at this scale. Past ~100k vectors, "
                     "swap in an ANN index (faiss/hnswlib) behind this same "
                     "search() — nothing else changes."),
        }


def make_index(store: Optional[VectorStore] = None):
    """An `index(key, item, source, vector)` for pipeline.ingest."""
    store = store or VectorStore()
    return lambda key, item, source, vector: store.add(key, item, source, vector)
