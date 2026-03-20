"""
Semantic Search Engine for Alibi Security

Enables natural language search across all stored camera analyses,
red flags, intelligence notes, and incidents.

Example queries:
- "person in red jacket near gate"
- "suspicious vehicle at night"
- "group of people running"
- "delivery truck blocking entrance"

Uses sentence-transformers for embedding + cosine similarity.
Falls back to TF-IDF if sentence-transformers is unavailable.
"""

import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

from alibi.encryption import get_encrypted_writer


@dataclass
class SearchResult:
    """A single search result."""
    source: str           # "camera_analysis", "red_flag", "intelligence", "vehicle", "face"
    score: float          # 0.0 to 1.0 similarity
    timestamp: str
    camera_id: str
    description: str
    snapshot_url: Optional[str]
    thumbnail_url: Optional[str]
    detected_objects: List[str]
    threat_level: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SemanticSearchEngine:
    """
    Semantic search over all stored security data.

    Embeds camera analysis descriptions using sentence-transformers
    (all-MiniLM-L6-v2, 384-d embeddings, ~80MB model).

    Index is built lazily on first search and cached in memory.
    Rebuilds automatically when new data is detected.
    """

    # Embedding cache file
    INDEX_PATH = Path("alibi/data/search_index.npz")

    def __init__(self):
        self._model = None
        self._use_transformer = False
        self._use_tfidf = False
        self._vectorizer = None
        self._tfidf_matrix = None

        self._embeddings: Optional[np.ndarray] = None
        self._records: List[Dict[str, Any]] = []
        self._index_count = 0
        self._last_build = 0.0

        self._crypto = get_encrypted_writer()

    def _load_model(self):
        """Load the embedding model (once)."""
        if self._model is not None or self._use_tfidf:
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._use_transformer = True
            print("[SemanticSearch] Loaded sentence-transformers model (all-MiniLM-L6-v2)")
        except ImportError:
            print("[SemanticSearch] sentence-transformers not available, falling back to TF-IDF")
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                self._vectorizer = TfidfVectorizer(
                    stop_words="english",
                    max_features=10000,
                    ngram_range=(1, 2),
                )
                self._use_tfidf = True
            except ImportError:
                print("[SemanticSearch] WARNING: Neither sentence-transformers nor sklearn available")

    def _build_index(self, force: bool = False):
        """
        Build the search index from all stored camera analyses + intelligence.

        Loads all JSONL records, creates embeddings, caches in memory.
        Only rebuilds if data has changed (checked by record count).
        """
        self._load_model()

        # Load all camera analyses
        analysis_path = Path("alibi/data/camera_analysis.jsonl")
        red_flags_path = Path("alibi/data/red_flags.jsonl")
        intel_notes_path = Path("alibi/data/intelligence_notes.jsonl")

        records = []

        # Camera analyses (primary source — richest descriptions)
        if analysis_path.exists():
            for data in self._crypto.read_lines(analysis_path):
                try:
                    desc = data.get("description", "")
                    objects = data.get("detected_objects", [])
                    activities = data.get("detected_activities", [])
                    meta = data.get("metadata", {})
                    threat = meta.get("threat_level", "safe")

                    # Build rich searchable text combining all metadata
                    parts = [desc]
                    if objects:
                        parts.append("Objects: " + ", ".join(objects))
                    if activities:
                        parts.append("Activities: " + ", ".join(activities))
                    if threat != "safe":
                        parts.append(f"Threat level: {threat}")
                    if meta.get("plates"):
                        for p in meta["plates"]:
                            parts.append(f"Vehicle plate: {p.get('plate_text', '')}")

                    search_text = ". ".join(parts)

                    records.append({
                        "source": "camera_analysis",
                        "search_text": search_text,
                        "timestamp": data.get("timestamp", ""),
                        "camera_id": data.get("camera_source", ""),
                        "description": desc,
                        "snapshot_url": data.get("snapshot_path"),
                        "thumbnail_url": data.get("thumbnail_path"),
                        "detected_objects": objects,
                        "threat_level": threat,
                        "metadata": {
                            "confidence": data.get("confidence", 0),
                            "method": data.get("method", ""),
                            "safety_concern": data.get("safety_concern", False),
                            "analysis_id": data.get("analysis_id", ""),
                        },
                    })
                except Exception:
                    continue

        # Red flags
        if red_flags_path.exists():
            for data in self._crypto.read_lines(red_flags_path):
                try:
                    desc = data.get("description", "")
                    tags = data.get("tags", [])
                    search_text = f"{desc}. Category: {data.get('category', '')}. Tags: {', '.join(tags)}"

                    records.append({
                        "source": "red_flag",
                        "search_text": search_text,
                        "timestamp": data.get("timestamp", ""),
                        "camera_id": data.get("location", ""),
                        "description": desc,
                        "snapshot_url": data.get("snapshot_url"),
                        "thumbnail_url": None,
                        "detected_objects": tags,
                        "threat_level": data.get("severity", "medium"),
                        "metadata": {
                            "flag_id": data.get("flag_id", ""),
                            "category": data.get("category", ""),
                            "resolved": data.get("resolved", False),
                        },
                    })
                except Exception:
                    continue

        # Intelligence notes
        if intel_notes_path.exists():
            for data in self._crypto.read_lines(intel_notes_path):
                try:
                    title = data.get("title", "")
                    content = data.get("content", "")
                    search_text = f"{title}. {content}"

                    records.append({
                        "source": "intelligence",
                        "search_text": search_text,
                        "timestamp": data.get("timestamp", ""),
                        "camera_id": "",
                        "description": f"{title}: {content[:200]}",
                        "snapshot_url": None,
                        "thumbnail_url": None,
                        "detected_objects": data.get("tags", []),
                        "threat_level": "info",
                        "metadata": {
                            "note_id": data.get("note_id", ""),
                            "category": data.get("category", ""),
                        },
                    })
                except Exception:
                    continue

        if not records:
            self._records = []
            self._embeddings = None
            self._index_count = 0
            return

        # Skip rebuild if nothing changed
        if not force and len(records) == self._index_count:
            return

        # Build embeddings
        texts = [r["search_text"] for r in records]

        if self._use_transformer and self._model is not None:
            embeddings = self._model.encode(
                texts,
                batch_size=64,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            self._embeddings = np.array(embeddings, dtype=np.float32)
        elif self._use_tfidf:
            self._tfidf_matrix = self._vectorizer.fit_transform(texts)
            self._embeddings = None  # TF-IDF uses sparse matrix
        else:
            # No embedding model — fall back to keyword matching
            self._embeddings = None

        self._records = records
        self._index_count = len(records)
        self._last_build = time.time()

        print(f"[SemanticSearch] Index built: {len(records)} records "
              f"({'transformer' if self._use_transformer else 'tfidf' if self._use_tfidf else 'keyword'})")

    def search(
        self,
        query: str,
        limit: int = 20,
        min_score: float = 0.15,
        source_filter: Optional[str] = None,
        camera_filter: Optional[str] = None,
        hours: Optional[int] = None,
        threat_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search all stored security data with natural language.

        Args:
            query: Natural language search query
            limit: Maximum results to return
            min_score: Minimum similarity score (0.0 to 1.0)
            source_filter: Filter by source type ("camera_analysis", "red_flag", "intelligence")
            camera_filter: Filter by camera ID
            hours: Only search within last N hours
            threat_filter: Filter by threat level ("caution", "warning", "critical")

        Returns:
            List of SearchResult objects sorted by relevance
        """
        self._build_index()

        if not self._records:
            return []

        # Compute similarities
        scores = self._compute_scores(query)

        # Build time cutoff
        cutoff = None
        if hours:
            cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Rank and filter results
        results = []
        for idx, score in enumerate(scores):
            if score < min_score:
                continue

            record = self._records[idx]

            # Apply filters
            if source_filter and record["source"] != source_filter:
                continue
            if camera_filter and camera_filter.lower() not in record["camera_id"].lower():
                continue
            if threat_filter and record["threat_level"] != threat_filter:
                continue

            if cutoff:
                try:
                    ts = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
                    if ts.replace(tzinfo=None) < cutoff:
                        continue
                except (ValueError, AttributeError):
                    pass

            results.append(SearchResult(
                source=record["source"],
                score=round(float(score), 4),
                timestamp=record["timestamp"],
                camera_id=record["camera_id"],
                description=record["description"],
                snapshot_url=record["snapshot_url"],
                thumbnail_url=record["thumbnail_url"],
                detected_objects=record["detected_objects"],
                threat_level=record["threat_level"],
                metadata=record["metadata"],
            ))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _compute_scores(self, query: str) -> np.ndarray:
        """Compute similarity scores for a query against the index."""
        n = len(self._records)

        if self._use_transformer and self._model is not None and self._embeddings is not None:
            # Sentence transformer cosine similarity
            query_emb = self._model.encode(
                [query], normalize_embeddings=True
            )
            scores = np.dot(self._embeddings, query_emb[0])
            return scores

        elif self._use_tfidf and self._tfidf_matrix is not None:
            # TF-IDF cosine similarity
            from sklearn.metrics.pairwise import cosine_similarity
            query_vec = self._vectorizer.transform([query])
            scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()
            return scores

        else:
            # Keyword fallback
            query_tokens = set(query.lower().split())
            query_tokens = {t for t in query_tokens if len(t) > 2}
            scores = np.zeros(n)

            for i, rec in enumerate(self._records):
                text_tokens = set(rec["search_text"].lower().split())
                text_tokens = {t for t in text_tokens if len(t) > 2}
                if query_tokens and text_tokens:
                    intersection = query_tokens & text_tokens
                    union = query_tokens | text_tokens
                    scores[i] = len(intersection) / len(union) if union else 0.0

            return scores

    def get_stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        self._build_index()

        by_source = {}
        for r in self._records:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1

        return {
            "total_indexed": self._index_count,
            "by_source": by_source,
            "index_type": (
                "sentence_transformer" if self._use_transformer
                else "tfidf" if self._use_tfidf
                else "keyword"
            ),
            "model": "all-MiniLM-L6-v2" if self._use_transformer else None,
            "last_build": datetime.fromtimestamp(self._last_build).isoformat() if self._last_build else None,
        }

    def rebuild_index(self) -> Dict[str, Any]:
        """Force rebuild the search index."""
        self._index_count = 0  # Force rebuild
        self._build_index(force=True)
        return self.get_stats()


# ── Global singleton ──────────────────────────────────────────

_engine: Optional[SemanticSearchEngine] = None


def get_semantic_search() -> SemanticSearchEngine:
    """Get the global SemanticSearchEngine instance."""
    global _engine
    if _engine is None:
        _engine = SemanticSearchEngine()
    return _engine
