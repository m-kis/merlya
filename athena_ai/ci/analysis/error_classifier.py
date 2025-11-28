"""
CI Error Classifier - Semantic classification using embeddings.

Reuses Athena's triage infrastructure (EmbeddingCache) for intelligent
error classification. No deterministic heuristics - uses semantic similarity.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from athena_ai.ci.models import CIErrorType
from athena_ai.utils.logger import logger

# Optional import for embeddings
try:
    import numpy as np

    from athena_ai.triage.smart_classifier.embedding_cache import EmbeddingCache

    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    np = None  # type: ignore
    EmbeddingCache = None  # type: ignore
    logger.debug("Embeddings not available for CI error classification")


@dataclass
class ClassificationResult:
    """Result of error classification."""

    error_type: CIErrorType
    confidence: float
    matched_pattern: str
    all_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class ErrorPattern:
    """Canonical error pattern for semantic matching."""

    error_type: CIErrorType
    description: str
    examples: List[str] = field(default_factory=list)


class CIErrorClassifier:
    """
    Semantic error classifier using embeddings.

    Uses sentence-transformers via EmbeddingCache to classify CI errors
    by semantic similarity rather than keyword matching.
    """

    # Canonical error patterns for semantic matching
    ERROR_PATTERNS: List[ErrorPattern] = [
        ErrorPattern(
            error_type=CIErrorType.TEST_FAILURE,
            description="Unit test, integration test, or end-to-end test failure",
            examples=[
                "FAILED tests/test_auth.py::test_login - AssertionError",
                "Test failed: expected 200 but got 404",
                "pytest: 3 failed, 10 passed",
                "jest: Test suite failed to run",
                "assertion error in test case",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.SYNTAX_ERROR,
            description="Code syntax error, parsing error, or invalid syntax",
            examples=[
                "SyntaxError: invalid syntax",
                "Unexpected token '}'",
                "Parse error: expected ';'",
                "IndentationError: unexpected indent",
                "error: expected expression before ')'",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.DEPENDENCY_ERROR,
            description="Package installation, import, or module resolution failure",
            examples=[
                "ModuleNotFoundError: No module named 'requests'",
                "npm ERR! Could not resolve dependency",
                "pip: No matching distribution found",
                "ImportError: cannot import name 'foo'",
                "Package 'xyz' not found in repository",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.PERMISSION_ERROR,
            description="Authentication, authorization, or access denied error",
            examples=[
                "Error: Resource not accessible by integration",
                "403 Forbidden: insufficient permissions",
                "Permission denied: cannot access repository",
                "GITHUB_TOKEN does not have required scopes",
                "Authentication failed: invalid token",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.TIMEOUT,
            description="Operation timeout, deadline exceeded, or slow execution",
            examples=[
                "Error: Timeout of 30000ms exceeded",
                "Operation timed out after 60 seconds",
                "The job exceeded the maximum time limit",
                "DeadlineExceeded: context deadline exceeded",
                "Process killed due to timeout",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.NETWORK_ERROR,
            description="Network connectivity, DNS, or connection failure",
            examples=[
                "Connection refused to host:port",
                "getaddrinfo ENOTFOUND registry.npmjs.org",
                "Could not resolve host: github.com",
                "Network is unreachable",
                "SSL certificate verification failed",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.RESOURCE_LIMIT,
            description="Out of memory, disk space, or resource quota exceeded",
            examples=[
                "Out of memory: JavaScript heap",
                "No space left on device",
                "Error: ENOMEM: not enough memory",
                "Disk quota exceeded",
                "Resource temporarily unavailable",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.TYPE_ERROR,
            description="Type checking failure, type mismatch, or typing error",
            examples=[
                "error TS2345: Argument type 'string' is not assignable",
                "mypy: error: Incompatible types",
                "TypeError: expected string, got int",
                "Type 'undefined' is not assignable to type 'string'",
                "error: incompatible types: int cannot be converted to String",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.LINT_ERROR,
            description="Linting, code style, or formatting violation",
            examples=[
                "eslint: 'foo' is defined but never used",
                "ruff: E501 line too long",
                "flake8: W503 line break before binary operator",
                "prettier: Code style issues found",
                "Error: Files were not formatted correctly",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.BUILD_FAILURE,
            description="Compilation, build process, or artifact creation failure",
            examples=[
                "error: compilation failed",
                "Build failed with exit code 1",
                "make: *** [target] Error 2",
                "cargo build failed",
                "gcc: error: unrecognized command line option",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.CONFIGURATION_ERROR,
            description="Invalid configuration, YAML syntax, or setup error",
            examples=[
                "Invalid workflow file: unexpected key",
                "Error parsing YAML: mapping values not allowed",
                "Configuration error: unknown property 'xyz'",
                "Invalid action reference: 'uses' is required",
                "Error: .gitlab-ci.yml is invalid",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.FLAKY_TEST,
            description="Intermittent test failure, race condition, or non-deterministic behavior",
            examples=[
                "Test passed on retry",
                "Flaky test detected: passed 2/3 runs",
                "Race condition: test order dependent",
                "Intermittent failure in async test",
                "Test occasionally fails due to timing",
            ],
        ),
        ErrorPattern(
            error_type=CIErrorType.INFRASTRUCTURE_ERROR,
            description="CI runner, container, or infrastructure failure",
            examples=[
                "Runner system failure",
                "Container failed to start",
                "The hosted runner encountered an error",
                "Job failed: System error",
                "Docker daemon not responding",
            ],
        ),
    ]

    def __init__(
        self,
        embedding_cache: Optional["EmbeddingCache"] = None,
        confidence_threshold: float = 0.5,
    ):
        """
        Initialize classifier.

        Args:
            embedding_cache: Shared embedding cache (creates new if not provided)
            confidence_threshold: Minimum confidence for classification
        """
        self._embedding_cache = embedding_cache
        self._confidence_threshold = confidence_threshold
        self._pattern_embeddings: Optional[Dict[CIErrorType, Any]] = None

    @property
    def embedding_cache(self) -> Optional["EmbeddingCache"]:
        """Get or create embedding cache."""
        if not HAS_EMBEDDINGS:
            return None

        if self._embedding_cache is None:
            self._embedding_cache = EmbeddingCache()

        return self._embedding_cache

    def _get_pattern_embeddings(self) -> Dict[CIErrorType, Any]:
        """Get or compute pattern embeddings."""
        if self._pattern_embeddings is not None:
            return self._pattern_embeddings

        if not self.embedding_cache:
            return {}

        self._pattern_embeddings = {}

        for pattern in self.ERROR_PATTERNS:
            # Combine description and examples for richer embedding
            texts = [pattern.description] + pattern.examples
            embeddings = self.embedding_cache.get_embeddings_batch(texts)

            # Average embeddings for this pattern
            avg_embedding = np.mean(embeddings, axis=0)
            self._pattern_embeddings[pattern.error_type] = avg_embedding

        logger.debug(f"Computed embeddings for {len(self._pattern_embeddings)} error patterns")
        return self._pattern_embeddings

    def classify(self, error_text: str) -> ClassificationResult:
        """
        Classify an error message.

        Args:
            error_text: Error message or log excerpt

        Returns:
            Classification result with error type and confidence
        """
        if not error_text or not error_text.strip():
            return ClassificationResult(
                error_type=CIErrorType.UNKNOWN,
                confidence=0.0,
                matched_pattern="",
            )

        # Use semantic classification if available
        if HAS_EMBEDDINGS and self.embedding_cache:
            return self._classify_semantic(error_text)

        # Fallback to simple heuristics
        return self._classify_fallback(error_text)

    def _classify_semantic(self, error_text: str) -> ClassificationResult:
        """Classify using semantic similarity."""
        try:
            pattern_embeddings = self._get_pattern_embeddings()
        except RuntimeError:
            # Embeddings not actually available - fallback
            return self._classify_fallback(error_text)

        if not pattern_embeddings:
            return self._classify_fallback(error_text)

        # Get embedding for error text
        error_embedding = self.embedding_cache.get_embedding(error_text)  # type: ignore

        # Compute similarities
        scores: Dict[str, float] = {}
        best_type = CIErrorType.UNKNOWN
        best_score = 0.0
        best_pattern = ""

        for error_type, pattern_embedding in pattern_embeddings.items():
            # Cosine similarity
            similarity = float(
                np.dot(error_embedding, pattern_embedding)
                / (np.linalg.norm(error_embedding) * np.linalg.norm(pattern_embedding))
            )

            # Normalize to 0-1 range (cosine can be -1 to 1)
            score = (similarity + 1) / 2
            scores[error_type.value] = score

            if score > best_score:
                best_score = score
                best_type = error_type
                # Find matching pattern description
                for p in self.ERROR_PATTERNS:
                    if p.error_type == error_type:
                        best_pattern = p.description
                        break

        # Apply threshold
        if best_score < self._confidence_threshold:
            best_type = CIErrorType.UNKNOWN
            best_pattern = "Low confidence classification"

        return ClassificationResult(
            error_type=best_type,
            confidence=best_score,
            matched_pattern=best_pattern,
            all_scores=scores,
        )

    def _classify_fallback(self, error_text: str) -> ClassificationResult:
        """Simple keyword-based fallback when embeddings unavailable."""
        text_lower = error_text.lower()

        # Simple keyword matching as fallback
        keyword_map: Dict[CIErrorType, List[str]] = {
            CIErrorType.TEST_FAILURE: ["test", "assert", "expect", "pytest", "jest", "failed"],
            CIErrorType.SYNTAX_ERROR: ["syntax", "parse", "unexpected token", "indentation"],
            CIErrorType.DEPENDENCY_ERROR: ["import", "module", "package", "dependency", "pip", "npm"],
            CIErrorType.PERMISSION_ERROR: ["permission", "denied", "403", "401", "token", "auth"],
            CIErrorType.TIMEOUT: ["timeout", "timed out", "deadline", "exceeded"],
            CIErrorType.NETWORK_ERROR: ["network", "connection", "unreachable", "dns", "ssl"],
            CIErrorType.RESOURCE_LIMIT: ["memory", "disk", "space", "quota", "oom"],
            CIErrorType.TYPE_ERROR: ["type", "typescript", "mypy", "typing", "ts2"],
            CIErrorType.LINT_ERROR: ["lint", "eslint", "ruff", "flake8", "style", "format"],
            CIErrorType.BUILD_FAILURE: ["build", "compile", "make", "cargo", "gcc"],
            CIErrorType.CONFIGURATION_ERROR: ["config", "yaml", "invalid", "workflow"],
        }

        best_type = CIErrorType.UNKNOWN
        best_count = 0

        for error_type, keywords in keyword_map.items():
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > best_count:
                best_count = count
                best_type = error_type

        confidence = min(0.3 + (best_count * 0.1), 0.7) if best_count > 0 else 0.0

        return ClassificationResult(
            error_type=best_type,
            confidence=confidence,
            matched_pattern="keyword-based fallback",
        )

    def classify_batch(self, error_texts: List[str]) -> List[ClassificationResult]:
        """
        Classify multiple error messages efficiently.

        Args:
            error_texts: List of error messages

        Returns:
            List of classification results
        """
        if not HAS_EMBEDDINGS or not self.embedding_cache:
            return [self._classify_fallback(text) for text in error_texts]

        # Batch compute embeddings for all texts
        valid_texts = [t for t in error_texts if t and t.strip()]
        if not valid_texts:
            return [
                ClassificationResult(CIErrorType.UNKNOWN, 0.0, "")
                for _ in error_texts
            ]

        embeddings = self.embedding_cache.get_embeddings_batch(valid_texts)
        pattern_embeddings = self._get_pattern_embeddings()

        results = []
        emb_idx = 0

        for text in error_texts:
            if not text or not text.strip():
                results.append(ClassificationResult(CIErrorType.UNKNOWN, 0.0, ""))
                continue

            error_embedding = embeddings[emb_idx]
            emb_idx += 1

            # Compute similarities
            best_type = CIErrorType.UNKNOWN
            best_score = 0.0
            best_pattern = ""
            all_scores: Dict[str, float] = {}

            for error_type, pattern_embedding in pattern_embeddings.items():
                similarity = float(
                    np.dot(error_embedding, pattern_embedding)
                    / (np.linalg.norm(error_embedding) * np.linalg.norm(pattern_embedding))
                )
                score = (similarity + 1) / 2
                all_scores[error_type.value] = score

                if score > best_score:
                    best_score = score
                    best_type = error_type
                    for p in self.ERROR_PATTERNS:
                        if p.error_type == error_type:
                            best_pattern = p.description
                            break

            if best_score < self._confidence_threshold:
                best_type = CIErrorType.UNKNOWN
                best_pattern = "Low confidence classification"

            results.append(
                ClassificationResult(
                    error_type=best_type,
                    confidence=best_score,
                    matched_pattern=best_pattern,
                    all_scores=all_scores,
                )
            )

        return results

    def get_suggestions(
        self,
        error_type: CIErrorType,
        error_text: str = "",
    ) -> List[str]:
        """
        Get fix suggestions for an error type.

        Args:
            error_type: Classified error type
            error_text: Original error text for context

        Returns:
            List of suggestions
        """
        suggestions: Dict[CIErrorType, List[str]] = {
            CIErrorType.TEST_FAILURE: [
                "Review failing test assertions and expected values",
                "Check for recent code changes that might have broken tests",
                "Run tests locally to reproduce and debug",
                "Look for race conditions in async tests",
            ],
            CIErrorType.SYNTAX_ERROR: [
                "Check for missing brackets, parentheses, or semicolons",
                "Verify indentation (especially in Python/YAML)",
                "Run a linter locally to find syntax issues",
            ],
            CIErrorType.DEPENDENCY_ERROR: [
                "Verify all dependencies are listed in manifest",
                "Check for version conflicts between packages",
                "Try clearing dependency cache and reinstalling",
                "Ensure private registry credentials are configured",
            ],
            CIErrorType.PERMISSION_ERROR: [
                "Check if token has required scopes/permissions",
                "Verify secrets are configured in repository settings",
                "Review workflow permissions configuration",
                "For forks, check if secrets are available",
            ],
            CIErrorType.TIMEOUT: [
                "Increase timeout limits in workflow configuration",
                "Optimize slow operations or split into smaller jobs",
                "Check for infinite loops or deadlocks",
                "Consider parallelizing independent operations",
            ],
            CIErrorType.NETWORK_ERROR: [
                "Check if external services are accessible",
                "Verify proxy/firewall settings",
                "Add retry logic for transient failures",
                "Check DNS resolution and SSL certificates",
            ],
            CIErrorType.RESOURCE_LIMIT: [
                "Increase memory limits in runner configuration",
                "Clean up artifacts between jobs",
                "Use a larger runner instance",
                "Optimize memory usage in build process",
            ],
            CIErrorType.TYPE_ERROR: [
                "Review type annotations and fix mismatches",
                "Update type stubs for external libraries",
                "Check for incorrect generic type parameters",
            ],
            CIErrorType.LINT_ERROR: [
                "Run linter locally and fix violations",
                "Update linter configuration if rules are too strict",
                "Use auto-fix options where available",
            ],
            CIErrorType.BUILD_FAILURE: [
                "Check build logs for specific compilation errors",
                "Verify build dependencies are installed",
                "Ensure build commands work locally",
            ],
            CIErrorType.CONFIGURATION_ERROR: [
                "Validate workflow file syntax",
                "Check for typos in job/step names",
                "Review action versions and inputs",
            ],
            CIErrorType.FLAKY_TEST: [
                "Add explicit waits for async operations",
                "Isolate test state to prevent interference",
                "Mark flaky tests and investigate root cause",
                "Consider running flaky tests in isolation",
            ],
            CIErrorType.INFRASTRUCTURE_ERROR: [
                "Check CI platform status page",
                "Retry the job after a delay",
                "Try using a different runner type",
                "Report persistent issues to platform support",
            ],
        }

        return suggestions.get(error_type, [
            "Review the error logs for more details",
            "Check recent changes that might have caused the failure",
            "Search for similar issues in project history",
        ])
