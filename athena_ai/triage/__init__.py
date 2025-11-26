"""
Triage System for Athena CLI.

Automatic incident prioritization (P0-P3) and intent classification.
Supports:
- AI-based classification (LLM, recommended)
- Semantic classification (embeddings, optional)
- Deterministic classification (keywords, fallback)
"""

from .ai_classifier import AITriageClassifier, get_ai_classifier
from .behavior import BEHAVIOR_PROFILES, BehaviorProfile, describe_behavior, get_behavior
from .classifier import PriorityClassifier, classify_priority, get_classifier
from .error_analyzer import ErrorAnalysis, ErrorAnalyzer, ErrorType, get_error_analyzer
from .priority import Intent, Priority, PriorityResult, TriageResult
from .signals import SignalDetector
from .smart_classifier import SmartTriageClassifier, get_smart_classifier, reset_smart_classifier

__all__ = [
    # Priority & Intent
    "Priority",
    "Intent",
    "PriorityResult",
    "TriageResult",
    # AI Classifier (recommended)
    "AITriageClassifier",
    "get_ai_classifier",
    # Detection (fallback)
    "SignalDetector",
    "PriorityClassifier",
    "classify_priority",
    "get_classifier",
    # Smart Classifier (embeddings)
    "SmartTriageClassifier",
    "get_smart_classifier",
    "reset_smart_classifier",
    # Behavior
    "BehaviorProfile",
    "BEHAVIOR_PROFILES",
    "get_behavior",
    "describe_behavior",
    # Error Analyzer
    "ErrorAnalyzer",
    "ErrorAnalysis",
    "ErrorType",
    "get_error_analyzer",
]
