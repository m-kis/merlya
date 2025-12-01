"""
Smart Triage Classifier.
"""

from typing import Any, Dict, List, Optional, Tuple

from merlya.utils.logger import logger

from ..priority import Intent, Priority, PriorityResult
from ..signals import SignalDetector
from .embedding_cache import HAS_EMBEDDINGS, EmbeddingCache
from .pattern_store import PatternStore

# Optional imports for embeddings
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore


class SmartTriageClassifier:
    """
    Intelligent triage classifier that learns from patterns.

    Features:
    - Semantic similarity using sentence-transformers
    - Pattern learning with FalkorDB
    - Fast keyword fallback when embeddings unavailable
    - Per-user personalization
    """

    def __init__(
        self,
        db_client=None,
        user_id: str = "default",
        use_embeddings: bool = True,
    ):
        """
        Initialize the smart classifier.

        Args:
            db_client: Optional FalkorDB client for pattern storage
            user_id: User identifier for personalized patterns
            use_embeddings: Whether to use embeddings (requires sentence-transformers)
        """
        self._signal_detector = SignalDetector()
        self._pattern_store = PatternStore(db_client, user_id)

        # Embedding support
        self._use_embeddings = use_embeddings and HAS_EMBEDDINGS
        self._embedding_cache: Optional[EmbeddingCache] = None
        if self._use_embeddings:
            self._embedding_cache = EmbeddingCache()

        # Reference patterns for semantic matching
        self._reference_patterns = self._build_reference_patterns()

        # Cache for reference embeddings (avoid lru_cache on instance method)
        # Stores (model_name, patterns, embeddings) to invalidate on model change
        self._reference_embeddings_cache: Dict[Intent, Tuple[str, List[str], Any]] = {}

    def _build_reference_patterns(self) -> Dict[Intent, List[str]]:
        """Build reference patterns for each intent."""
        return {
            Intent.QUERY: [
                "quels sont mes serveurs",
                "liste les hosts",
                "montre moi les services",
                "what are my servers",
                "list hosts",
                "show me the services",
                "combien de serveurs",
                "where is the database",
            ],
            Intent.ACTION: [
                "redémarre le service nginx",
                "vérifie le disque",
                "exécute la commande",
                "restart the nginx service",
                "check the disk",
                "execute the command",
                "deploy the application",
                "start the container",
            ],
            Intent.ANALYSIS: [
                "analyse la performance",
                "pourquoi le service est lent",
                "diagnostique le problème",
                "analyze the performance",
                "why is the service slow",
                "diagnose the problem",
                "investigate the error",
                "troubleshoot the issue",
            ],
        }

    def _get_reference_embeddings(self, intent: Intent) -> Tuple[List[str], Optional["np.ndarray"]]:
        """Get cached reference embeddings for an intent."""
        if not self._use_embeddings or not self._embedding_cache:
            return [], None

        current_model = self._embedding_cache.model_name

        # Use instance-level cache instead of lru_cache (avoids memory leak)
        # Check if cache entry exists and model matches
        if intent in self._reference_embeddings_cache:
            cached_model, patterns, embeddings = self._reference_embeddings_cache[intent]
            if cached_model == current_model:
                return patterns, embeddings
            # Model changed - invalidate this cache entry
            del self._reference_embeddings_cache[intent]
            logger.debug(f"Invalidated reference embeddings for {intent.value}: model changed {cached_model} → {current_model}")

        patterns = self._reference_patterns[intent]
        embeddings = self._embedding_cache.get_embeddings_batch(patterns)
        result_embeddings = np.array(embeddings)
        self._reference_embeddings_cache[intent] = (current_model, patterns, result_embeddings)
        return patterns, result_embeddings

    def _semantic_intent_score(self, query: str) -> Dict[Intent, float]:
        """
        Calculate semantic similarity scores for each intent.

        Returns dict of intent -> similarity score (0-1).
        """
        if not self._use_embeddings or not self._embedding_cache:
            return {}

        try:
            query_embedding = self._embedding_cache.get_embedding(query)
            scores = {}

            for intent in Intent:
                _, ref_embeddings = self._get_reference_embeddings(intent)
                if ref_embeddings is None or len(ref_embeddings) == 0:
                    continue

                # Cosine similarity with zero-norm protection
                query_norm = np.linalg.norm(query_embedding)
                if query_norm == 0:
                    # Zero vector - skip semantic scoring
                    continue

                ref_norms = np.linalg.norm(ref_embeddings, axis=1)
                # Avoid division by zero for any reference embedding
                valid_mask = ref_norms > 0
                if not np.any(valid_mask):
                    continue

                similarities = np.dot(ref_embeddings[valid_mask], query_embedding) / (
                    ref_norms[valid_mask] * query_norm
                )
                # Use max similarity as score
                scores[intent] = float(np.max(similarities))

            return scores

        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")
            return {}

    def classify(
        self,
        query: str,
        system_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Intent, PriorityResult]:
        """
        Classify intent and priority for a query.

        Uses a multi-layer approach:
        1. Check stored patterns (fastest)
        2. Keyword detection
        3. Semantic similarity (if available)
        4. Combine scores with weighted voting

        Args:
            query: User query text
            system_state: Optional system metrics for priority

        Returns:
            (intent, priority_result)
        """
        # Layer 1: Check stored patterns (threshold: 0.7 for implicitly validated)
        stored = self._pattern_store.find_similar_patterns(query, limit=1)
        if stored and stored[0].get("confidence", 0) >= 0.7:
            # High confidence stored pattern
            pattern = stored[0]
            try:
                intent = Intent(pattern["intent"])
                priority = Priority[pattern["priority"]]

                # Still run priority classification for signals
                priority_result = self._classify_priority(query, priority, system_state)
                return intent, priority_result
            except (ValueError, KeyError) as e:
                # Invalid enum value in DB (corrupted/outdated data) - fall through to fresh classification
                logger.warning(f"Invalid stored pattern data, reclassifying: {e}")

        # Layer 2: Keyword detection
        kw_intent, kw_conf, kw_signals = self._signal_detector.detect_intent(query)

        # Layer 3: Semantic similarity (if available)
        semantic_scores = self._semantic_intent_score(query)

        # Combine scores
        final_intent = self._combine_intent_scores(
            kw_intent, kw_conf, semantic_scores
        )

        # Priority classification
        priority_result = self._classify_priority(query, None, system_state)

        # Store pattern for learning (low confidence until confirmed)
        # Only store if not already stored (avoid duplicates)
        if self._pattern_store.is_available and not stored:
            embedding = None
            if self._use_embeddings and self._embedding_cache:
                embedding = self._embedding_cache.get_embedding(query).tolist()

            self._pattern_store.store_pattern(
                query,
                final_intent,
                priority_result.priority,
                embedding=embedding,
                confidence=0.5,  # Initial low confidence
            )

        return final_intent, priority_result

    def _combine_intent_scores(
        self,
        kw_intent: Intent,
        kw_confidence: float,
        semantic_scores: Dict[Intent, float],
    ) -> Intent:
        """Combine keyword and semantic scores to determine final intent."""
        # If no semantic scores, use keyword only
        if not semantic_scores:
            return kw_intent

        # Weighted combination
        # Keywords: 0.4, Semantic: 0.6
        combined_scores = {}

        for intent in Intent:
            kw_score = kw_confidence if intent == kw_intent else 0.0
            sem_score = semantic_scores.get(intent, 0.0)
            combined_scores[intent] = 0.4 * kw_score + 0.6 * sem_score

        return max(combined_scores, key=lambda k: combined_scores[k])

    def _classify_priority(
        self,
        query: str,
        override_priority: Optional[Priority],
        system_state: Optional[Dict[str, Any]],
    ) -> PriorityResult:
        """Run priority classification using SignalDetector."""
        from ..classifier import PriorityClassifier

        classifier = PriorityClassifier()
        result = classifier.classify(query, system_state=system_state)

        if override_priority is not None:
            result.priority = override_priority

        return result

    def provide_feedback(
        self,
        query: str,
        correct_intent: Intent,
        correct_priority: Priority,
    ) -> bool:
        """
        Provide feedback to improve future classifications.

        Call this when the user corrects a classification.
        """
        return self._pattern_store.update_pattern_feedback(
            query, correct_intent, correct_priority
        )

    def confirm_classification(self, query: str) -> bool:
        """
        Confirm a classification was useful (implicit positive feedback).

        Call this when a classification is used successfully without correction.
        Gradually increases confidence until pattern becomes trusted.

        Example: After agent completes a task successfully, call this
        to reinforce the classification that was used.
        """
        return self._pattern_store.increment_pattern_confidence(query)

    def get_stats(self) -> Dict[str, Any]:
        """Get classifier statistics."""
        return {
            "embeddings_available": self._use_embeddings,
            "pattern_store": self._pattern_store.get_stats(),
        }
