"""
Relation Classifier Package.
"""

import threading
from typing import Optional

from .classifier import HostRelationClassifier
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


__all__ = ["HostRelationClassifier", "get_relation_classifier", "RelationSuggestion"]
