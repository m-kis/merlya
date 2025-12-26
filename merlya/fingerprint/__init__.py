"""
Merlya Fingerprint Module.

Provides semantic signature extraction for commands and operations.
Used for approval caching and risk assessment.
"""

from merlya.fingerprint.cache import ApprovalScope, FingerprintCache
from merlya.fingerprint.extractor import SemanticSignatureExtractor
from merlya.fingerprint.models import SemanticSignature

__all__ = [
    "ApprovalScope",
    "FingerprintCache",
    "SemanticSignature",
    "SemanticSignatureExtractor",
]
