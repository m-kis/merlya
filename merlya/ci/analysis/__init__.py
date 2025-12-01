"""
CI Analysis Module - Semantic error classification and analysis.

Reuses Merlya's triage infrastructure (EmbeddingCache) for intelligent
error classification without deterministic heuristics.
"""

from merlya.ci.analysis.error_classifier import CIErrorClassifier

__all__ = ["CIErrorClassifier"]
