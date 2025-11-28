"""
Factory functions for Smart Triage Classifier.
"""

from typing import Dict, Optional, Tuple

from .classifier import SmartTriageClassifier

# Singleton instances per (db_client_id, user_id) combination
_smart_classifiers: Dict[Tuple[int, str], SmartTriageClassifier] = {}


def get_smart_classifier(
    db_client=None,
    user_id: str = "default",
    force_new: bool = False,
) -> SmartTriageClassifier:
    """
    Get or create a smart classifier instance.

    Creates separate instances for different db_client/user_id combinations.
    Reuses existing instances for the same combination unless force_new=True.

    Args:
        db_client: FalkorDB client for pattern storage
        user_id: User identifier for personalized patterns
        force_new: If True, create a new instance even if one exists

    Returns:
        SmartTriageClassifier instance
    """
    # Use id(db_client) to distinguish different client instances
    cache_key = (id(db_client) if db_client else 0, user_id)

    if force_new or cache_key not in _smart_classifiers:
        _smart_classifiers[cache_key] = SmartTriageClassifier(
            db_client=db_client,
            user_id=user_id,
        )

    return _smart_classifiers[cache_key]


def reset_smart_classifier(user_id: Optional[str] = None) -> None:
    """
    Reset cached classifier instances.

    Args:
        user_id: If provided, only reset instances for this user.
                 If None, reset all instances.
    """
    global _smart_classifiers
    if user_id is None:
        _smart_classifiers.clear()
    else:
        # Remove only instances matching user_id
        keys_to_remove = [k for k in _smart_classifiers if k[1] == user_id]
        for key in keys_to_remove:
            del _smart_classifiers[key]
