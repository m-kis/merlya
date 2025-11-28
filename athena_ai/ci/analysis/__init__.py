"""
CI Analysis Module - Semantic error classification and analysis.

Reuses Athena's triage infrastructure (EmbeddingCache) for intelligent
error classification without deterministic heuristics.
"""

from athena_ai.ci.analysis.error_classifier import CIErrorClassifier

__all__ = ["CIErrorClassifier"]
