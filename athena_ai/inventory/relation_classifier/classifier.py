"""
Host Relation Classifier.
"""

import threading
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

from .heuristics import RelationHeuristics
from .llm import LLMRelationExtractor
from .models import RelationSuggestion


class HostRelationClassifier:
    """
    Suggests relations between hosts.

    Uses a hybrid approach:
    1. Heuristic rules for common patterns (fast, high confidence)
    2. LLM for complex patterns (when heuristics find few relations)

    Relation types:
    - cluster_member: Hosts in the same cluster (e.g., web-01, web-02)
    - database_replica: Database replication (e.g., db-master, db-replica)
    - depends_on: Service dependency
    - backup_of: Backup relationship
    - load_balanced: Hosts behind same load balancer
    - related_service: Related services
    """

    def __init__(self, llm_router: Optional[Any] = None):
        """Initialize classifier with optional LLM router.

        Args:
            llm_router: Optional pre-configured LLM router. If None, will be
                        lazy-loaded on first access.

        Internal state for _llm:
            - None: Not yet initialized (will attempt lazy load)
            - False: Initialization failed (won't retry)
            - LLMRouter instance: Successfully initialized
        """
        self._llm: Any = llm_router  # None means "not initialized yet"
        self._llm_extractor: Optional[LLMRelationExtractor] = None
        if llm_router:
            self._llm_extractor = LLMRelationExtractor(llm_router)

    @property
    def llm(self) -> Optional[Any]:
        """Lazy load LLM router (only attempts initialization once).

        Returns:
            LLMRouter instance if available, None if initialization failed.
        """
        # False sentinel indicates prior initialization failure - don't retry
        if self._llm is False:
            return None

        # None means not yet initialized - attempt lazy load
        if self._llm is None:
            try:
                from athena_ai.llm.router import LLMRouter
                self._llm = LLMRouter()
                self._llm_extractor = LLMRelationExtractor(self._llm)
            except Exception as e:
                logger.warning(f"Could not initialize LLM router: {e}")
                # Set False sentinel to prevent repeated initialization attempts
                self._llm = False
                return None

        return self._llm

    def suggest_relations(
        self,
        hosts: List[Dict[str, Any]],
        existing_relations: Optional[List[Dict]] = None,
        use_llm: bool = True,
        min_confidence: float = 0.5,
    ) -> List[RelationSuggestion]:
        """
        Suggest relations between hosts.

        Args:
            hosts: List of host dictionaries
            existing_relations: Already known relations to exclude
            use_llm: Whether to use LLM for complex patterns
            min_confidence: Minimum confidence threshold

        Returns:
            List of relation suggestions sorted by confidence
        """
        suggestions = []

        # 1. Heuristic-based relations (fast)
        suggestions.extend(RelationHeuristics.find_cluster_relations(hosts))
        suggestions.extend(RelationHeuristics.find_replica_relations(hosts))
        suggestions.extend(RelationHeuristics.find_group_relations(hosts))
        suggestions.extend(RelationHeuristics.find_service_relations(hosts))

        # 2. LLM-based relations (if few heuristic results)
        if use_llm and len(suggestions) < 5 and len(hosts) > 2:
            # Ensure LLM is initialized
            if self.llm and self._llm_extractor:
                llm_suggestions = self._llm_extractor.extract_relations(hosts)
                suggestions.extend(llm_suggestions)

        # Filter by confidence
        suggestions = [s for s in suggestions if s.confidence >= min_confidence]

        # Remove duplicates
        suggestions = self._deduplicate(suggestions)

        # Filter out existing relations
        if existing_relations:
            suggestions = self._filter_existing(suggestions, existing_relations)

        # Sort by confidence
        suggestions.sort(key=lambda x: x.confidence, reverse=True)

        return suggestions

    def _deduplicate(self, suggestions: List[RelationSuggestion]) -> List[RelationSuggestion]:
        """Remove duplicate suggestions, keeping the highest-confidence instance."""
        best_by_key: Dict[tuple, RelationSuggestion] = {}

        for s in suggestions:
            # Create a normalized key (order-independent for bidirectional relations)
            # Normalize to lowercase for case-insensitive comparison
            src_lower = s.source_hostname.lower()
            tgt_lower = s.target_hostname.lower()
            if s.relation_type in ["cluster_member", "load_balanced"]:
                key = tuple(sorted([src_lower, tgt_lower])) + (s.relation_type,)
            else:
                key = (src_lower, tgt_lower, s.relation_type)

            # Keep the suggestion with the highest confidence for each key
            if key not in best_by_key or s.confidence > best_by_key[key].confidence:
                best_by_key[key] = s

        return list(best_by_key.values())

    def _filter_existing(
        self,
        suggestions: List[RelationSuggestion],
        existing: List[Dict],
    ) -> List[RelationSuggestion]:
        """Filter out suggestions that already exist."""
        existing_keys = set()
        for rel in existing:
            key = (
                rel.get("source_hostname", "").lower(),
                rel.get("target_hostname", "").lower(),
                rel.get("relation_type", ""),
            )
            existing_keys.add(key)
            # Also add reverse for bidirectional relation types only
            if rel.get("relation_type") in ["cluster_member", "load_balanced"]:
                existing_keys.add((key[1], key[0], key[2]))

        return [
            s for s in suggestions
            if (s.source_hostname.lower(), s.target_hostname.lower(), s.relation_type) not in existing_keys
        ]
