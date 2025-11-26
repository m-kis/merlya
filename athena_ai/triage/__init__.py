"""
Triage System for Athena CLI.

Automatic incident prioritization (P0-P3) and intent classification.
Supports both deterministic (keyword) and semantic (embedding) classification.
"""

from .behavior import BEHAVIOR_PROFILES, BehaviorProfile, describe_behavior, get_behavior
from .classifier import PriorityClassifier, classify_priority, get_classifier
from .priority import Intent, Priority, PriorityResult, TriageResult
from .signals import SignalDetector
from .smart_classifier import SmartTriageClassifier, get_smart_classifier, reset_smart_classifier

__all__ = [
    # Priority & Intent
    "Priority",
    "Intent",
    "PriorityResult",
    "TriageResult",
    # Detection
    "SignalDetector",
    "PriorityClassifier",
    "classify_priority",
    "get_classifier",
    # Smart Classifier
    "SmartTriageClassifier",
    "get_smart_classifier",
    "reset_smart_classifier",
    # Behavior
    "BehaviorProfile",
    "BEHAVIOR_PROFILES",
    "get_behavior",
    "describe_behavior",
]
