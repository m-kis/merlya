"""
Semantic Variable Query Detector.

Uses sentence-transformers to detect if a query is about user @variables.
Falls back to keyword detection if embeddings unavailable.
"""
from typing import Optional, Tuple

from merlya.utils.logger import logger

from .smart_classifier.embedding_cache import HAS_EMBEDDINGS, EmbeddingCache

# Optional numpy
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore


class VariableQueryDetector:
    """
    Detects if a query is about Merlya user variables (@variables).

    Uses semantic similarity with reference patterns when embeddings are available,
    falls back to keyword matching otherwise.

    Example usage:
        detector = VariableQueryDetector()
        is_variable_query, confidence = detector.detect("affiche moi la variable @Test")
        # Returns (True, 0.85)
    """

    # Reference patterns for variable-related queries (FR + EN)
    VARIABLE_PATTERNS = [
        # French patterns
        "affiche moi la variable",
        "quelle est la valeur de la variable",
        "montre moi les variables",
        "liste les variables",
        "qu'est-ce qu'il y a dans la variable",
        "affiche le contenu de la variable",
        "donne moi la valeur de",
        # English patterns
        "show me the variable",
        "what is the value of the variable",
        "list my variables",
        "display the variables",
        "what is in the variable",
        "show the variable content",
        "get the value of",
        # Direct @variable patterns
        "show @",
        "affiche @",
        "value of @",
        "valeur de @",
    ]

    # Threshold for semantic similarity (0-1)
    # Set high to avoid false positives on general queries
    SIMILARITY_THRESHOLD = 0.78

    def __init__(self, use_embeddings: bool = True):
        """
        Initialize the detector.

        Args:
            use_embeddings: Whether to use semantic matching (requires sentence-transformers)
        """
        self._use_embeddings = use_embeddings and HAS_EMBEDDINGS
        self._embedding_cache: Optional[EmbeddingCache] = None
        self._reference_embeddings: Optional["np.ndarray"] = None
        self._current_model: Optional[str] = None

        if self._use_embeddings:
            try:
                self._embedding_cache = EmbeddingCache()
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize embeddings for variable detection: {e}")
                self._use_embeddings = False

    def _ensure_reference_embeddings(self) -> Optional["np.ndarray"]:
        """Lazy-load and cache reference embeddings."""
        if not self._use_embeddings or not self._embedding_cache:
            return None

        # Check if model changed (invalidate cache)
        current_model = self._embedding_cache.model_name
        if self._reference_embeddings is not None and self._current_model == current_model:
            return self._reference_embeddings

        # Compute reference embeddings
        try:
            embeddings = self._embedding_cache.get_embeddings_batch(self.VARIABLE_PATTERNS)
            self._reference_embeddings = np.array(embeddings)
            self._current_model = current_model
            logger.debug(f"📊 Loaded {len(self.VARIABLE_PATTERNS)} reference patterns for variable detection")
            return self._reference_embeddings
        except Exception as e:
            logger.warning(f"⚠️ Failed to compute reference embeddings: {e}")
            return None

    def _semantic_match(self, query: str) -> Tuple[bool, float]:
        """
        Check if query semantically matches variable patterns.

        Returns:
            (is_match, confidence)
        """
        ref_embeddings = self._ensure_reference_embeddings()
        if ref_embeddings is None or not self._embedding_cache:
            return False, 0.0

        try:
            # Get query embedding
            query_embedding = self._embedding_cache.get_embedding(query)

            # Compute cosine similarities
            query_norm = np.linalg.norm(query_embedding)
            if query_norm == 0:
                return False, 0.0

            ref_norms = np.linalg.norm(ref_embeddings, axis=1)
            valid_mask = ref_norms > 0
            if not np.any(valid_mask):
                return False, 0.0

            similarities = np.dot(ref_embeddings[valid_mask], query_embedding) / (
                ref_norms[valid_mask] * query_norm
            )

            max_similarity = float(np.max(similarities))
            is_match = max_similarity >= self.SIMILARITY_THRESHOLD

            return is_match, max_similarity

        except Exception as e:
            logger.warning(f"⚠️ Semantic matching failed: {e}")
            return False, 0.0

    def _keyword_match(self, query: str) -> Tuple[bool, float]:
        """
        Fallback keyword-based detection.

        Returns:
            (is_match, confidence)
        """
        query_lower = query.lower()

        # Exclude command contexts where @ is a hostname reference, not a variable query
        # Examples: "/healthcheck @hostname", "check status on @server"
        command_patterns = [
            "/healthcheck",
            "/hc",
            "/health",
            "/incident",
            "/inc",
            "/ssh",
            "check status",
            "connect to",
            "run on",
            "execute on",
            "scan",
        ]
        for pattern in command_patterns:
            if pattern in query_lower and "@" in query_lower:
                # This is a command with a hostname reference, not a variable query
                return False, 0.0

        # Strong indicators - but only "variable" keywords, not bare "@"
        # The "@" alone is ambiguous (could be hostname reference)
        strong_keywords = [
            "variable",
            "variables",
        ]

        for kw in strong_keywords:
            if kw in query_lower:
                return True, 0.8

        # Check for @ only if it looks like a variable query context
        # "show me @Test" vs "@server" alone
        if "@" in query_lower:
            # Only match if there's an explicit query about the variable
            variable_query_words = ["show", "affiche", "display", "what is", "value of", "get"]
            for word in variable_query_words:
                if word in query_lower:
                    return True, 0.75
            # Bare "@hostname" without query context is NOT a variable query
            return False, 0.0

        # Medium indicators (need context)
        medium_patterns = [
            ("affiche", "valeur"),
            ("montre", "valeur"),
            ("show", "value"),
            ("display", "value"),
            ("list", "defined"),
        ]

        for p1, p2 in medium_patterns:
            if p1 in query_lower and p2 in query_lower:
                return True, 0.7

        return False, 0.0

    def detect(self, query: str) -> Tuple[bool, float]:
        """
        Detect if query is about user variables.

        Args:
            query: User query text

        Returns:
            (is_variable_query, confidence)
            - is_variable_query: True if query is about @variables
            - confidence: 0.0 to 1.0 confidence score
        """
        # Try semantic matching first
        if self._use_embeddings:
            is_match, confidence = self._semantic_match(query)
            if is_match:
                logger.debug(f"📊 Variable query detected (semantic): confidence={confidence:.2f}")
                return True, confidence

        # Fall back to keyword matching
        is_match, confidence = self._keyword_match(query)
        if is_match:
            logger.debug(f"📊 Variable query detected (keyword): confidence={confidence:.2f}")
            return True, confidence

        return False, 0.0

    def get_context_hint(self) -> str:
        """Get the context hint message for variable queries."""
        return """📌 **VARIABLE QUERY DETECTED**
This query is about user-defined @variables in Merlya.
Use get_user_variables() to list all variables, or get_variable_value(name) to get a specific one.
Variables are set via `/variables set <key> <value>` and can be used as @key in queries."""

    @property
    def is_semantic_enabled(self) -> bool:
        """Check if semantic matching is available."""
        return self._use_embeddings


# Singleton instance for reuse
_detector: Optional[VariableQueryDetector] = None


def get_variable_detector() -> VariableQueryDetector:
    """Get or create the singleton variable detector."""
    global _detector
    if _detector is None:
        _detector = VariableQueryDetector()
    return _detector


def detect_variable_query(query: str) -> Tuple[bool, float]:
    """
    Convenience function to detect if a query is about variables.

    Args:
        query: User query text

    Returns:
        (is_variable_query, confidence)
    """
    return get_variable_detector().detect(query)
