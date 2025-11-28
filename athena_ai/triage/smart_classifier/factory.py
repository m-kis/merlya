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
    cache_key = (id(db_client) if db_client else 0, user_id)

    with _lock:
        if force_new or cache_key not in _smart_classifiers:
            classifier = SmartTriageClassifier(
                db_client=db_client,
                user_id=user_id,
            )
            # Store both classifier and db_client reference to prevent GC
            _smart_classifiers[cache_key] = (classifier, db_client)

        return _smart_classifiers[cache_key][0]


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
