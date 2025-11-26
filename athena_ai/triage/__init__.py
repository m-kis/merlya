"""
Triage System for Athena CLI.

Automatic incident prioritization (P0-P3) with behavior profiles.
"""

from .behavior import BEHAVIOR_PROFILES, BehaviorProfile, describe_behavior, get_behavior
from .classifier import PriorityClassifier, classify_priority, get_classifier
from .priority import Priority, PriorityResult
from .signals import SignalDetector

__all__ = [
    "Priority",
    "PriorityResult",
    "SignalDetector",
    "PriorityClassifier",
    "classify_priority",
    "get_classifier",
    "BehaviorProfile",
    "BEHAVIOR_PROFILES",
    "get_behavior",
    "describe_behavior",
]
