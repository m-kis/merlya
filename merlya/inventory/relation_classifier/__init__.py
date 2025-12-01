"""
Relation Classifier Package.

Uses a 3-tier approach for host relation discovery:
1. Embeddings (PRIMARY) - Local safetensors model via sentence-transformers
2. LLM (FALLBACK) - Cloud LLM for complex patterns
3. Heuristics (LAST RESORT) - Rule-based pattern matching
"""

import threading
from typing import Optional

from .classifier import HostRelationClassifier
from .embeddings import EmbeddingRelationExtractor
from .models import RelationSuggestion

# Thread-safe singleton
_classifier: Optional[HostRelationClassifier] = None
_classifier_lock = threading.Lock()


def get_relation_classifier() -> HostRelationClassifier:
    """Get the relation classifier singleton (thread-safe)."""
    global _classifier
    if _classifier is None:
        with _classifier_lock:
            # Double-checked locking pattern
            if _classifier is None:
                _classifier = HostRelationClassifier()
    return _classifier


__all__ = [
    "HostRelationClassifier",
    "EmbeddingRelationExtractor",
    "get_relation_classifier",
    "RelationSuggestion",
]
