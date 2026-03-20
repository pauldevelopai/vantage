"""
Training Example Selector

Selects relevant training examples from the collected training data
and formats them as few-shot context for scene analysis prompts.

This closes the training loop: collected examples → better analysis.
"""

import json
import math
from pathlib import Path
from typing import List, Dict, Optional
from collections import Counter

from alibi.training_agent import SecurityTrainingExample, TRAINING_AGENT_DATA


class TrainingExampleSelector:
    """
    Selects training examples most relevant to a current scene description
    and formats them as few-shot prompt context for the scene analyzer.

    Uses TF-IDF cosine similarity when sklearn is available,
    falls back to Jaccard keyword overlap otherwise.
    """

    def __init__(self, training_data_path: str = None):
        self._path = Path(training_data_path) if training_data_path else TRAINING_AGENT_DATA
        self._examples: List[SecurityTrainingExample] = []
        self._use_tfidf = False
        self._tfidf_matrix = None
        self._vectorizer = None
        self._loaded = False

    def _ensure_loaded(self):
        """Lazy-load examples and build index on first use."""
        if self._loaded:
            return
        self._loaded = True

        if not self._path.exists():
            print("[TrainingSelector] No training data file found")
            return

        # Load examples
        with open(self._path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._examples.append(SecurityTrainingExample(**data))
                except Exception:
                    continue

        if not self._examples:
            print("[TrainingSelector] No training examples loaded")
            return

        print(f"[TrainingSelector] Loaded {len(self._examples)} training examples")

        # Try to build TF-IDF index
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine

            descriptions = [ex.scene_description for ex in self._examples]
            self._vectorizer = TfidfVectorizer(
                stop_words='english',
                max_features=5000,
                ngram_range=(1, 2),
            )
            self._tfidf_matrix = self._vectorizer.fit_transform(descriptions)
            self._use_tfidf = True
            print("[TrainingSelector] TF-IDF index built (sklearn)")
        except ImportError:
            print("[TrainingSelector] sklearn not available, using keyword fallback")

    def select_relevant(self, current_description: str, top_n: int = 3) -> List[SecurityTrainingExample]:
        """
        Find the top-N most relevant training examples for a given scene description.

        Args:
            current_description: The current scene description to match against
            top_n: Number of examples to return

        Returns:
            List of most relevant SecurityTrainingExample objects
        """
        self._ensure_loaded()

        if not self._examples or top_n <= 0:
            return []

        if self._use_tfidf:
            return self._select_tfidf(current_description, top_n)
        else:
            return self._select_jaccard(current_description, top_n)

    def _select_tfidf(self, description: str, top_n: int) -> List[SecurityTrainingExample]:
        """Select using TF-IDF cosine similarity."""
        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = self._vectorizer.transform([description])
        similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        # Get top-N indices (sorted by similarity descending)
        top_indices = similarities.argsort()[-top_n:][::-1]

        results = []
        for idx in top_indices:
            if similarities[idx] > 0.05:  # Minimum relevance threshold
                results.append(self._examples[idx])

        return results

    def _select_jaccard(self, description: str, top_n: int) -> List[SecurityTrainingExample]:
        """Fallback: select using Jaccard keyword overlap."""
        query_tokens = set(description.lower().split())
        # Remove very short tokens
        query_tokens = {t for t in query_tokens if len(t) > 2}

        scored = []
        for ex in self._examples:
            ex_tokens = set(ex.scene_description.lower().split())
            ex_tokens = {t for t in ex_tokens if len(t) > 2}

            if not query_tokens or not ex_tokens:
                continue

            intersection = query_tokens & ex_tokens
            union = query_tokens | ex_tokens
            jaccard = len(intersection) / len(union) if union else 0.0

            if jaccard > 0.05:
                scored.append((jaccard, ex))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:top_n]]

    def format_as_few_shot(self, examples: List[SecurityTrainingExample]) -> str:
        """
        Format selected examples as few-shot prompt context.

        Args:
            examples: List of training examples to format

        Returns:
            Formatted string for injection into LLM prompts
        """
        if not examples:
            return ""

        lines = ["", "Reference examples from similar security scenes:"]
        for i, ex in enumerate(examples, 1):
            # Truncate long descriptions
            desc = ex.scene_description[:200]
            relevance = ex.security_relevance[:100]
            lines.append(
                f"  {i}. Scene: \"{desc}\" | "
                f"Assessment: \"{relevance}\" | "
                f"Category: {ex.category}"
            )
        lines.append("")

        return "\n".join(lines)

    def get_context_for_scene(self, current_description: str, top_n: int = 3) -> str:
        """
        Convenience method: select relevant examples and format as prompt context.

        Args:
            current_description: Current scene description
            top_n: Number of examples to include

        Returns:
            Formatted few-shot context string (empty string if no relevant examples)
        """
        examples = self.select_relevant(current_description, top_n)
        return self.format_as_few_shot(examples)

    def get_stats(self) -> Dict:
        """Return statistics about the training example index."""
        self._ensure_loaded()

        if not self._examples:
            return {
                "total_examples": 0,
                "index_type": "none",
                "by_category": {},
            }

        categories = Counter(ex.category for ex in self._examples)

        return {
            "total_examples": len(self._examples),
            "index_type": "tfidf" if self._use_tfidf else "jaccard",
            "by_category": dict(categories),
        }


# Global singleton
_selector: Optional[TrainingExampleSelector] = None


def get_training_selector() -> TrainingExampleSelector:
    """Get the global TrainingExampleSelector instance."""
    global _selector
    if _selector is None:
        _selector = TrainingExampleSelector()
    return _selector
