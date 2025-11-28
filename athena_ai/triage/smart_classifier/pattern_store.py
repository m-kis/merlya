"""
Pattern Store for Smart Triage Classifier.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

from ..priority import Intent, Priority


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

            return result or []

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
