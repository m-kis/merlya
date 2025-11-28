"""
Factory functions for Smart Triage Classifier.
"""

import threading
from typing import Any, Dict, Optional, Tuple

from .classifier import SmartTriageClassifier

# Cache structure: (db_client_id, user_id) -> (classifier, db_client_ref)
# We keep a reference to db_client to prevent GC and ID reuse issues
_smart_classifiers: Dict[Tuple[int, str], Tuple[SmartTriageClassifier, Any]] = {}
_lock = threading.Lock()


def get_smart_classifier(
    db_client=None,
    user_id: str = "default",
    force_new: bool = False,
) -> SmartTriageClassifier:
    """
    Get or create a smart classifier instance.

    Creates separate instances for different db_client/user_id combinations.
    Reuses existing instances for the same combination unless force_new=True.

    Thread-safe implementation that prevents cache collisions from ID reuse
    after garbage collection.

    Args:
        db_client: FalkorDB client for pattern storage
        user_id: User identifier for personalized patterns
        force_new: If True, create a new instance even if one exists

    Returns:
        SmartTriageClassifier instance
    """
    with _lock:
        # Compute cache_key inside lock to prevent db_client GC during computation
        cache_key = (id(db_client) if db_client else 0, user_id)

        # Check for cached instance and verify it's the same object (not just same ID)
        if not force_new and cache_key in _smart_classifiers:
            cached_classifier, cached_db_client = _smart_classifiers[cache_key]
            if cached_db_client is db_client:
                return cached_classifier
            # ID collision after GC - evict stale entry
            del _smart_classifiers[cache_key]

        # Create new instance
        classifier = SmartTriageClassifier(
            db_client=db_client,
            user_id=user_id,
        )
        _smart_classifiers[cache_key] = (classifier, db_client)
        return classifier


def reset_smart_classifier(user_id: Optional[str] = None) -> None:
    """
    Reset cached classifier instances.

    Args:
        user_id: If provided, only reset instances for this user.
                 If None, reset all instances.
    """
    with _lock:
        if user_id is None:
            _smart_classifiers.clear()
        else:
            # Remove only instances matching user_id
            keys_to_remove = [k for k in _smart_classifiers if k[1] == user_id]
            for key in keys_to_remove:
                del _smart_classifiers[key]
