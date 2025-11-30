"""
Error Analyzer with Semantic Classification.

Uses sentence-transformers (local model) for semantic similarity to detect
error types (credentials, connection, permission, etc.) without fixed patterns.

Similar architecture to SmartTriageClassifier but specialized for error analysis.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from athena_ai.utils.logger import logger

from .smart_classifier import HAS_EMBEDDINGS, EmbeddingCache

if HAS_EMBEDDINGS:
    import numpy as np


class ErrorType(Enum):
    """Types of errors that can be detected."""

    CREDENTIAL = "credential"  # Authentication/password errors
    CONNECTION = "connection"  # Network/connectivity errors
    PERMISSION = "permission"  # Access denied/privilege errors
    NOT_FOUND = "not_found"  # Resource not found
    TIMEOUT = "timeout"  # Timeout errors
    RESOURCE = "resource"  # Resource exhaustion (disk, memory)
    CONFIGURATION = "configuration"  # Config/syntax errors
    UNKNOWN = "unknown"  # Unclassified errors


@dataclass
class ErrorAnalysis:
    """Result of error analysis."""

    error_type: ErrorType
    confidence: float
    needs_credentials: bool
    suggested_action: str
    original_error: str
    matched_pattern: Optional[str] = None


class ErrorAnalyzer:
    """
    Semantic error analyzer using local embeddings.

    Uses sentence-transformers to classify errors by comparing against
    reference error patterns. No API calls - runs entirely locally.
    """

    def __init__(self, use_embeddings: bool = True):
        """
        Initialize the error analyzer.

        Args:
            use_embeddings: Whether to use embeddings (requires sentence-transformers)
        """
        self._use_embeddings = use_embeddings and HAS_EMBEDDINGS
        self._embedding_cache: Optional[EmbeddingCache] = None

        if self._use_embeddings:
            self._embedding_cache = EmbeddingCache()

        # Reference patterns for each error type
        self._reference_patterns = self._build_reference_patterns()
        self._reference_embeddings_cache: Dict[ErrorType, Tuple[List[str], Any]] = {}

        # Keyword patterns for fallback
        self._keyword_patterns = self._build_keyword_patterns()

        # Actions for each error type
        self._suggested_actions = {
            ErrorType.CREDENTIAL: "Verify credentials or provide authentication",
            ErrorType.CONNECTION: "Check network connectivity and host availability",
            ErrorType.PERMISSION: "Check user permissions or run with elevated privileges",
            ErrorType.NOT_FOUND: "Verify the resource path or name exists",
            ErrorType.TIMEOUT: "Increase timeout or check service responsiveness",
            ErrorType.RESOURCE: "Free up system resources (disk, memory)",
            ErrorType.CONFIGURATION: "Review configuration syntax and values",
            ErrorType.UNKNOWN: "Review the error message for more details",
        }

    def _build_keyword_patterns(self) -> Dict[ErrorType, List[str]]:
        """Build simple keyword patterns for fallback matching."""
        return {
            ErrorType.CREDENTIAL: [
                "authentication failed",
                "access denied",
                "invalid password",
                "login failed",
                "unauthorized",
                "permission denied (publickey",
                "password authentication failed",
                "invalid credentials",
                "invalid api key",
                "token expired",
            ],
            ErrorType.CONNECTION: [
                "connection refused",
                "connection timed out",
                "no route to host",
                "network is unreachable",
                "could not resolve",
                "unable to connect",
                "econnrefused",
                "ehostunreach",
            ],
            ErrorType.PERMISSION: [
                "permission denied",
                "operation not permitted",
                "insufficient privileges",
                "403 forbidden",
                "eacces",
                "eperm",
            ],
            ErrorType.NOT_FOUND: [
                "no such file",
                "file not found",
                "command not found",
                "404 not found",
                "enoent",
                "does not exist",
            ],
            ErrorType.TIMEOUT: [
                "timed out",
                "timeout",
                "deadline exceeded",
            ],
            ErrorType.RESOURCE: [
                "no space left",
                "out of memory",
                "cannot allocate",
                "too many open files",
                "disk full",
            ],
            ErrorType.CONFIGURATION: [
                "syntax error",
                "invalid configuration",
                "parse error",
                "invalid value",
            ],
        }

    def _build_reference_patterns(self) -> Dict[ErrorType, List[str]]:
        """Build reference error patterns for semantic matching."""
        return {
            ErrorType.CREDENTIAL: [
                # SSH/Authentication
                "Permission denied (publickey,password)",
                "Authentication failed",
                "Invalid password",
                "Access denied",
                "Login incorrect",
                "Bad password",
                "Incorrect username or password",
                "Authentication required",
                "Credentials are invalid",
                "Password authentication failed",
                "Could not authenticate",
                "Auth failure",
                "Login failed",
                "Invalid credentials",
                "Unauthorized access",
                # Database
                "password authentication failed",
                "Access denied for user",
                "Login failed for user",
                "Invalid username/password",
                "Authentication error",
                "FATAL: password authentication failed",
                "OperationalError: FATAL: password",
                "mysql access denied",
                "mongodb authentication failed",
                # API/Token
                "Invalid API key",
                "Token expired",
                "Invalid token",
                "Unauthorized",
                "401 Unauthorized",
                "Invalid bearer token",
            ],
            ErrorType.CONNECTION: [
                "Connection refused",
                "Connection timed out",
                "No route to host",
                "Network is unreachable",
                "Host unreachable",
                "Connection reset by peer",
                "Could not resolve hostname",
                "Name or service not known",
                "Unable to connect",
                "Connection failed",
                "Socket error",
                "ECONNREFUSED",
                "ETIMEDOUT",
                "EHOSTUNREACH",
                "Network error",
                "Cannot connect to",
                "Failed to establish connection",
                "Connection closed",
                "Remote host closed connection",
                "SSH connection failed",
            ],
            ErrorType.PERMISSION: [
                "Permission denied",
                "Operation not permitted",
                "Access is denied",
                "Insufficient privileges",
                "You don't have permission",
                "EACCES",
                "EPERM",
                "Forbidden",
                "403 Forbidden",
                "sudo required",
                "must be root",
                "requires elevated privileges",
                "insufficient permissions",
                "read-only file system",
                "cannot write to",
            ],
            ErrorType.NOT_FOUND: [
                "No such file or directory",
                "File not found",
                "Directory not found",
                "Command not found",
                "Module not found",
                "Package not found",
                "Resource not found",
                "404 Not Found",
                "ENOENT",
                "does not exist",
                "not found",
                "cannot find",
                "missing file",
                "No such host",
                "Unknown host",
            ],
            ErrorType.TIMEOUT: [
                "Timed out",
                "Timeout exceeded",
                "Operation timed out",
                "Connection timed out",
                "Read timed out",
                "Request timeout",
                "408 Request Timeout",
                "504 Gateway Timeout",
                "Deadline exceeded",
                "Took too long",
                "Execution expired",
            ],
            ErrorType.RESOURCE: [
                "No space left on device",
                "Disk full",
                "Out of memory",
                "Cannot allocate memory",
                "Memory allocation failed",
                "Too many open files",
                "ENOMEM",
                "ENOSPC",
                "Resource temporarily unavailable",
                "Process limit exceeded",
                "Quota exceeded",
                "Storage full",
            ],
            ErrorType.CONFIGURATION: [
                "Syntax error",
                "Invalid configuration",
                "Parse error",
                "Configuration error",
                "Invalid value",
                "Missing required",
                "Unknown option",
                "Invalid option",
                "Malformed",
                "Expected",
                "Unexpected token",
                "Invalid format",
            ],
        }

    def _get_reference_embeddings(
        self, error_type: ErrorType
    ) -> Tuple[List[str], Optional["np.ndarray"]]:
        """Get cached reference embeddings for an error type."""
        if not self._use_embeddings or not self._embedding_cache:
            return [], None

        if error_type in self._reference_embeddings_cache:
            return self._reference_embeddings_cache[error_type]

        patterns = self._reference_patterns.get(error_type, [])
        if not patterns:
            return [], None

        embeddings = self._embedding_cache.get_embeddings_batch(patterns)
        result = (patterns, np.array(embeddings))
        self._reference_embeddings_cache[error_type] = result
        return result

    def _keyword_match(self, error_text: str) -> Tuple[ErrorType, float, Optional[str]]:
        """
        Simple keyword-based error classification (fallback).

        Returns (error_type, confidence, matched_keyword).
        """
        error_lower = error_text.lower()

        best_type = ErrorType.UNKNOWN
        best_confidence = 0.0
        best_match = None

        for error_type, keywords in self._keyword_patterns.items():
            for keyword in keywords:
                if keyword in error_lower:
                    # Longer matches = higher confidence
                    confidence = min(0.9, 0.7 + len(keyword) / 100)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_type = error_type
                        best_match = keyword

        return best_type, best_confidence, best_match

    def _semantic_error_scores(self, error_text: str) -> Dict[ErrorType, Tuple[float, Optional[str]]]:
        """
        Calculate semantic similarity scores for each error type.

        Returns dict of error_type -> (similarity_score, best_matching_pattern).
        """
        if not self._use_embeddings or not self._embedding_cache:
            return {}

        try:
            error_embedding = self._embedding_cache.get_embedding(error_text)
            scores: Dict[ErrorType, Tuple[float, Optional[str]]] = {}

            for error_type in ErrorType:
                if error_type == ErrorType.UNKNOWN:
                    continue

                patterns, ref_embeddings = self._get_reference_embeddings(error_type)
                if ref_embeddings is None or len(ref_embeddings) == 0:
                    continue

                # Cosine similarity with zero-norm protection
                error_norm = np.linalg.norm(error_embedding)
                if error_norm == 0:
                    continue

                ref_norms = np.linalg.norm(ref_embeddings, axis=1)
                valid_mask = ref_norms > 0
                if not np.any(valid_mask):
                    continue

                similarities = np.dot(ref_embeddings[valid_mask], error_embedding) / (
                    ref_norms[valid_mask] * error_norm
                )

                max_idx = np.argmax(similarities)
                max_score = float(similarities[max_idx])

                # Get the pattern that matched best
                valid_patterns = [p for p, v in zip(patterns, valid_mask, strict=True) if v]
                best_pattern = valid_patterns[max_idx] if valid_patterns else None

                scores[error_type] = (max_score, best_pattern)

            return scores

        except Exception as e:
            logger.warning(f"Semantic error scoring failed: {e}")
            return {}

    def analyze(self, error_text: str) -> ErrorAnalysis:
        """
        Analyze an error message and classify its type.

        Args:
            error_text: The error message to analyze

        Returns:
            ErrorAnalysis with type, confidence, and suggested action
        """
        if not error_text or not error_text.strip():
            return ErrorAnalysis(
                error_type=ErrorType.UNKNOWN,
                confidence=0.0,
                needs_credentials=False,
                suggested_action=self._suggested_actions[ErrorType.UNKNOWN],
                original_error=error_text or "",
            )

        # Get semantic scores (if embeddings available)
        scores = self._semantic_error_scores(error_text)

        if not scores:
            # No embeddings - use keyword fallback
            kw_type, kw_conf, kw_match = self._keyword_match(error_text)
            if kw_conf >= 0.6:
                return ErrorAnalysis(
                    error_type=kw_type,
                    confidence=kw_conf,
                    needs_credentials=(kw_type == ErrorType.CREDENTIAL),
                    suggested_action=self._suggested_actions[kw_type],
                    original_error=error_text,
                    matched_pattern=kw_match,
                )
            return ErrorAnalysis(
                error_type=ErrorType.UNKNOWN,
                confidence=0.0,
                needs_credentials=False,
                suggested_action=self._suggested_actions[ErrorType.UNKNOWN],
                original_error=error_text,
            )

        # Find best match
        best_type = max(scores, key=lambda t: scores[t][0])
        best_score, best_pattern = scores[best_type]

        # Threshold for classification (0.6 = reasonable match)
        if best_score < 0.6:
            return ErrorAnalysis(
                error_type=ErrorType.UNKNOWN,
                confidence=best_score,
                needs_credentials=False,
                suggested_action=self._suggested_actions[ErrorType.UNKNOWN],
                original_error=error_text,
            )

        # Check if credentials are needed
        needs_credentials = best_type == ErrorType.CREDENTIAL

        return ErrorAnalysis(
            error_type=best_type,
            confidence=best_score,
            needs_credentials=needs_credentials,
            suggested_action=self._suggested_actions[best_type],
            original_error=error_text,
            matched_pattern=best_pattern,
        )

    def needs_credentials(self, error_text: str) -> bool:
        """
        Quick check if an error indicates credential issues.

        Args:
            error_text: The error message to check

        Returns:
            True if credentials are likely needed
        """
        analysis = self.analyze(error_text)
        return analysis.needs_credentials and analysis.confidence >= 0.6

    def get_error_type(self, error_text: str) -> ErrorType:
        """
        Get the classified error type.

        Args:
            error_text: The error message to classify

        Returns:
            The detected ErrorType
        """
        return self.analyze(error_text).error_type


# Singleton instance
_error_analyzer: Optional[ErrorAnalyzer] = None


def get_error_analyzer(force_new: bool = False) -> ErrorAnalyzer:
    """
    Get or create the error analyzer singleton.

    Args:
        force_new: If True, create a new instance

    Returns:
        ErrorAnalyzer instance
    """
    global _error_analyzer

    if force_new or _error_analyzer is None:
        _error_analyzer = ErrorAnalyzer()

    return _error_analyzer
