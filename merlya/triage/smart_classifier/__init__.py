"""
Smart Triage Classifier Package.
"""

from .classifier import SmartTriageClassifier
from .embedding_cache import HAS_EMBEDDINGS, EmbeddingCache, get_embedding_cache, reset_embedding_cache
from .factory import get_smart_classifier, reset_smart_classifier
from .pattern_store import PatternStore

# Re-export for backwards compatibility
DEFAULT_MODEL = "paraphrase-MiniLM-L3-v2"

__all__ = [
    "SmartTriageClassifier",
    "get_smart_classifier",
    "reset_smart_classifier",
    "EmbeddingCache",
    "get_embedding_cache",
    "reset_embedding_cache",
    "PatternStore",
    "DEFAULT_MODEL",
    "HAS_EMBEDDINGS",
]
