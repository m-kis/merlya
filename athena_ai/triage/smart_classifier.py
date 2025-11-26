"""
Smart Triage Classifier with Semantic Learning.

Uses sentence-transformers for semantic similarity and FalkorDB for pattern storage.
Learns from user feedback to improve classification over time.

Falls back to keyword-based classification if embeddings unavailable.
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from athena_ai.utils.logger import logger

from .priority import Intent, Priority, PriorityResult
from .signals import SignalDetector

# Optional imports for embeddings
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    np = None  # type: ignore
    logger.debug("sentence-transformers not installed. Using keyword-only classification.")


# Model name - small and fast, good for intent classification
DEFAULT_MODEL = "paraphrase-MiniLM-L3-v2"  # 17MB, very fast


class EmbeddingCache:
    """LRU cache for text embeddings to avoid recomputation."""

    def __init__(self, model_name: str = DEFAULT_MODEL, max_size: int = 1000):
        self._model: Optional["SentenceTransformer"] = None
        self._model_name = model_name
        self._cache: Dict[str, "np.ndarray"] = {}
        self._max_size = max_size
        self._access_order: List[str] = []

    @property
    def model(self) -> "SentenceTransformer":
        """Lazy load the model."""
        if self._model is None:
            logger.info(f"Loading embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _get_key(self, text: str) -> str:
        """Generate cache key from text."""
        return hashlib.md5(text.lower().strip().encode()).hexdigest()

    def get_embedding(self, text: str) -> "np.ndarray":
        """Get embedding for text, using cache if available."""
        key = self._get_key(text)

        if key in self._cache:
            # Move to end of access order
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]

        # Compute embedding
        embedding = self.model.encode(text, convert_to_numpy=True)

        # Cache it
        self._cache[key] = embedding
        self._access_order.append(key)

        # Evict if over max size
        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]

        return embedding

    def get_embeddings_batch(self, texts: List[str]) -> List["np.ndarray"]:
        """Get embeddings for multiple texts efficiently."""
        # Split into cached and uncached
        cached = []
        uncached = []
        uncached_indices = []

        for i, text in enumerate(texts):
            key = self._get_key(text)
            if key in self._cache:
                # Update access order for cache hit (LRU behavior)
                if key in self._access_order:
                    self._access_order.remove(key)
                self._access_order.append(key)
                cached.append((i, self._cache[key]))
            else:
                uncached.append(text)
                uncached_indices.append(i)

        # Batch compute uncached
        if uncached:
            new_embeddings = self.model.encode(uncached, convert_to_numpy=True)
            for idx, text, embedding in zip(uncached_indices, uncached, new_embeddings):
                key = self._get_key(text)
                self._cache[key] = embedding
                self._access_order.append(key)
                cached.append((idx, embedding))

        # Maintain cache size
        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]

        # Sort by original index and return
        cached.sort(key=lambda x: x[0])
        return [emb for _, emb in cached]


class PatternStore:
    """
    FalkorDB-backed storage for learned triage patterns.

    Stores:
    - User query patterns with their intent/priority
    - Embeddings for semantic similarity search
    - Feedback (correct/incorrect) for learning
    """

    def __init__(self, db_client=None, user_id: str = "default"):
        self._db = db_client
        self._user_id = user_id
        self._initialized = False

    @property
    def is_available(self) -> bool:
        """Check if FalkorDB is available."""
        return self._db is not None and self._db.is_connected

    def _ensure_schema(self) -> None:
        """Ensure the triage pattern schema exists."""
        if self._initialized or not self.is_available:
            return

        try:
            # Create indexes for fast lookup
            self._db.query(
                "CREATE INDEX IF NOT EXISTS FOR (p:TriagePattern) ON (p.user_id)"
            )
            self._db.query(
                "CREATE INDEX IF NOT EXISTS FOR (p:TriagePattern) ON (p.intent)"
            )
            self._initialized = True
        except Exception as e:
            logger.warning(f"Failed to create triage schema: {e}")

    def store_pattern(
        self,
        query: str,
        intent: Intent,
        priority: Priority,
        embedding: Optional[List[float]] = None,
        confidence: float = 1.0,
    ) -> bool:
        """
        Store or update a triage pattern (upsert).

        Confidence levels:
        - 0.5: Auto-classified (not used for predictions)
        - 0.7: Implicitly validated (no correction after use)
        - 1.0: User confirmed via /feedback

        Args:
            query: The user query text
            intent: Detected intent
            priority: Detected priority
            embedding: Optional embedding vector
            confidence: Confidence score (1.0 = user confirmed)
        """
        if not self.is_available:
            return False

        self._ensure_schema()

        try:
            # Normalize query for matching
            normalized = query.lower().strip()

            # Store embedding as comma-separated string (FalkorDB limitation)
            embedding_str = ",".join(map(str, embedding)) if embedding else ""

            # Use MERGE to upsert: create if not exists, update if exists
            cypher = """
                MERGE (p:TriagePattern {user_id: $user_id, query: $query})
                ON CREATE SET
                    p.intent = $intent,
                    p.priority = $priority,
                    p.embedding = $embedding,
                    p.confidence = $confidence,
                    p.use_count = 1,
                    p.created_at = $created_at
                ON MATCH SET
                    p.use_count = p.use_count + 1
                RETURN p
            """
            self._db.query(cypher, {
                "user_id": self._user_id,
                "query": normalized,
                "intent": intent.value,
                "priority": priority.name,
                "embedding": embedding_str,
                "confidence": confidence,
                "created_at": datetime.now().isoformat(),
            })
            return True

        except Exception as e:
            logger.warning(f"Failed to store pattern: {e}")
            return False

    def find_similar_patterns(
        self,
        query: str,
        intent: Optional[Intent] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Find patterns similar to the given query.

        Uses exact match first, then falls back to prefix/substring matching.
        Embedding similarity would require a separate vector DB.
        """
        if not self.is_available:
            return []

        self._ensure_schema()
        normalized = query.lower().strip()

        # Validate and sanitize limit (Cypher doesn't support parameterized LIMIT)
        # Safety: ensure it's an int in valid range before string interpolation
        limit = max(1, min(int(limit), 100))

        try:
            # Build params dict - use parameters to prevent Cypher injection
            # Note: LIMIT cannot be parameterized in Cypher, but we validated it above
            params = {"user_id": self._user_id, "query": normalized}

            # Build WHERE clause with optional intent filter
            if intent:
                params["intent_val"] = intent.value
                where_clause = "p.user_id = $user_id AND p.query = $query AND p.intent = $intent_val"
            else:
                where_clause = "p.user_id = $user_id AND p.query = $query"

            # Try exact match first
            result = self._db.query(
                f"""
                MATCH (p:TriagePattern)
                WHERE {where_clause}
                RETURN p.query as query, p.intent as intent, p.priority as priority,
                       p.confidence as confidence, p.use_count as use_count
                LIMIT {limit}
                """,
                params,
            )

            if result:
                return result

            # Try prefix match
            params["prefix"] = normalized[:20]
            if intent:
                prefix_where = "p.user_id = $user_id AND p.query STARTS WITH $prefix AND p.intent = $intent_val"
            else:
                prefix_where = "p.user_id = $user_id AND p.query STARTS WITH $prefix"

            result = self._db.query(
                f"""
                MATCH (p:TriagePattern)
                WHERE {prefix_where}
                RETURN p.query as query, p.intent as intent, p.priority as priority,
                       p.confidence as confidence, p.use_count as use_count
                ORDER BY p.confidence DESC, p.use_count DESC
                LIMIT {limit}
                """,
                params,
            )

            return result

        except Exception as e:
            logger.warning(f"Failed to find patterns: {e}")
            return []

    def increment_pattern_confidence(self, query: str) -> bool:
        """
        Increment confidence for a pattern (implicit positive feedback).

        Called when a classification is used without correction.
        Increases confidence by 0.1 up to 0.8 (never reaches user-confirmed 1.0).
        """
        if not self.is_available:
            return False

        normalized = query.lower().strip()

        try:
            existing = self._db.find_node(
                "TriagePattern",
                {"user_id": self._user_id, "query": normalized},
            )

            if existing:
                current_conf = existing.get("confidence", 0.5)
                # Only increment if below implicit validation threshold
                if current_conf < 0.8:
                    self._db.update_node(
                        "TriagePattern",
                        {"user_id": self._user_id, "query": normalized},
                        {
                            "confidence": min(0.8, current_conf + 0.1),
                            "use_count": existing.get("use_count", 1) + 1,
                        },
                    )
                    return True
            return False

        except Exception as e:
            logger.warning(f"Failed to increment confidence: {e}")
            return False

    def update_pattern_feedback(
        self,
        query: str,
        correct_intent: Intent,
        correct_priority: Priority,
    ) -> bool:
        """
        Update a pattern based on user feedback.

        Increases confidence if correct, creates new pattern if incorrect.
        """
        if not self.is_available:
            return False

        normalized = query.lower().strip()

        try:
            # Check if pattern exists
            existing = self._db.find_node(
                "TriagePattern",
                {"user_id": self._user_id, "query": normalized},
            )

            if existing:
                # Update existing pattern
                if (
                    existing.get("intent") == correct_intent.value
                    and existing.get("priority") == correct_priority.name
                ):
                    # Correct - increase confidence and use count
                    self._db.update_node(
                        "TriagePattern",
                        {"user_id": self._user_id, "query": normalized},
                        {
                            "confidence": min(1.0, existing.get("confidence", 0.5) + 0.1),
                            "use_count": existing.get("use_count", 1) + 1,
                        },
                    )
                else:
                    # Incorrect - update with correct values
                    self._db.update_node(
                        "TriagePattern",
                        {"user_id": self._user_id, "query": normalized},
                        {
                            "intent": correct_intent.value,
                            "priority": correct_priority.name,
                            "confidence": 1.0,  # User confirmed
                        },
                    )
            else:
                # Create new pattern
                self.store_pattern(
                    query,
                    correct_intent,
                    correct_priority,
                    confidence=1.0,
                )

            return True

        except Exception as e:
            logger.warning(f"Failed to update pattern: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored patterns."""
        if not self.is_available:
            return {"available": False}

        try:
            # Count patterns by intent
            intent_counts = {}
            for intent in Intent:
                result = self._db.query(
                    """
                    MATCH (p:TriagePattern)
                    WHERE p.user_id = $user_id AND p.intent = $intent
                    RETURN count(p) as count
                    """,
                    {"user_id": self._user_id, "intent": intent.value},
                )
                intent_counts[intent.value] = result[0].get("count", 0) if result else 0

            # Total patterns
            total_result = self._db.query(
                """
                MATCH (p:TriagePattern)
                WHERE p.user_id = $user_id
                RETURN count(p) as count
                """,
                {"user_id": self._user_id},
            )
            total = total_result[0].get("count", 0) if total_result else 0

            return {
                "available": True,
                "user_id": self._user_id,
                "total_patterns": total,
                "by_intent": intent_counts,
            }

        except Exception as e:
            logger.warning(f"Failed to get stats: {e}")
            return {"available": True, "error": str(e)}


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
        self._reference_embeddings_cache: Dict[Intent, Tuple[List[str], Any]] = {}

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

        # Use instance-level cache instead of lru_cache (avoids memory leak)
        if intent in self._reference_embeddings_cache:
            return self._reference_embeddings_cache[intent]

        patterns = self._reference_patterns[intent]
        embeddings = self._embedding_cache.get_embeddings_batch(patterns)
        result = (patterns, np.array(embeddings))
        self._reference_embeddings_cache[intent] = result
        return result

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

        return max(combined_scores, key=combined_scores.get)

    def _classify_priority(
        self,
        query: str,
        override_priority: Optional[Priority],
        system_state: Optional[Dict[str, Any]],
    ) -> PriorityResult:
        """Run priority classification using SignalDetector."""
        from .classifier import PriorityClassifier

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


# Singleton instances per (db_client_id, user_id) combination
_smart_classifiers: Dict[Tuple[int, str], SmartTriageClassifier] = {}


def get_smart_classifier(
    db_client=None,
    user_id: str = "default",
    force_new: bool = False,
) -> SmartTriageClassifier:
    """
    Get or create a smart classifier instance.

    Creates separate instances for different db_client/user_id combinations.
    Reuses existing instances for the same combination unless force_new=True.

    Args:
        db_client: FalkorDB client for pattern storage
        user_id: User identifier for personalized patterns
        force_new: If True, create a new instance even if one exists

    Returns:
        SmartTriageClassifier instance
    """
    # Use id(db_client) to distinguish different client instances
    cache_key = (id(db_client) if db_client else 0, user_id)

    if force_new or cache_key not in _smart_classifiers:
        _smart_classifiers[cache_key] = SmartTriageClassifier(
            db_client=db_client,
            user_id=user_id,
        )

    return _smart_classifiers[cache_key]


def reset_smart_classifier(user_id: Optional[str] = None) -> None:
    """
    Reset cached classifier instances.

    Args:
        user_id: If provided, only reset instances for this user.
                 If None, reset all instances.
    """
    global _smart_classifiers
    if user_id is None:
        _smart_classifiers.clear()
    else:
        # Remove only instances matching user_id
        keys_to_remove = [k for k in _smart_classifiers if k[1] == user_id]
        for key in keys_to_remove:
            del _smart_classifiers[key]
