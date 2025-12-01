"""
Host Relation Classifier.

Uses a 3-tier approach for relation discovery:
1. Embeddings (PRIMARY) - Local safetensors model, fast, offline, privacy-preserving
2. LLM (FALLBACK) - Cloud LLM for complex patterns when embeddings insufficient
3. Heuristics (LAST RESORT) - Rule-based patterns as final fallback
"""

from typing import Any, Dict, List, Optional

from merlya.utils.logger import logger

from .embeddings import EmbeddingRelationExtractor
from .heuristics import RelationHeuristics
from .llm import LLMRelationExtractor
from .models import RelationSuggestion


class HostRelationClassifier:
    """
    Suggests relations between hosts using a 3-tier approach.

    Tier 1 (PRIMARY): Local Embeddings
        - Uses sentence-transformers (safetensors)
        - Fast, runs locally, works offline
        - Semantic similarity between hostname patterns

    Tier 2 (FALLBACK): Cloud LLM
        - Uses configured LLM (task: correction for cost efficiency)
        - Called only if embeddings find < MIN_EMBEDDING_RESULTS
        - Better for complex/unusual patterns

    Tier 3 (LAST RESORT): Heuristics
        - Deterministic rule-based patterns
        - Always runs to catch obvious patterns
        - Merged with other results

    Relation types:
    - cluster_member: Hosts in the same cluster (e.g., web-01, web-02)
    - database_replica: Database replication (e.g., db-master, db-replica)
    - depends_on: Service dependency
    - backup_of: Backup relationship
    - load_balanced: Hosts behind same load balancer
    - related_service: Related services
    """

    # Minimum results from embeddings before falling back to LLM
    MIN_EMBEDDING_RESULTS = 3

    # Minimum hosts required for LLM analysis (avoid API calls for tiny inventories)
    MIN_HOSTS_FOR_LLM = 5

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
        self._embedding_extractor: Optional[EmbeddingRelationExtractor] = None

        if llm_router:
            self._llm_extractor = LLMRelationExtractor(llm_router)

    @property
    def embedding_extractor(self) -> EmbeddingRelationExtractor:
        """Lazy load embedding extractor."""
        if self._embedding_extractor is None:
            self._embedding_extractor = EmbeddingRelationExtractor()
        return self._embedding_extractor

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
                from merlya.llm.router import LLMRouter
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
        use_embeddings: bool = True,
        min_confidence: float = 0.5,
    ) -> List[RelationSuggestion]:
        """
        Suggest relations between hosts using 3-tier approach.

        Order of operations:
        1. Embeddings (PRIMARY) - Always tried first if available
        2. LLM (FALLBACK) - Only if embeddings insufficient
        3. Heuristics (ALWAYS) - Merged to catch obvious patterns

        Args:
            hosts: List of host dictionaries
            existing_relations: Already known relations to exclude
            use_llm: Whether to allow LLM fallback
            use_embeddings: Whether to use embeddings (default True)
            min_confidence: Minimum confidence threshold

        Returns:
            List of relation suggestions sorted by confidence
        """
        suggestions: List[RelationSuggestion] = []
        used_methods: List[str] = []

        # ═══════════════════════════════════════════════════════════════
        # TIER 1: Embeddings (PRIMARY) - Local, fast, offline
        # ═══════════════════════════════════════════════════════════════
        if use_embeddings and self.embedding_extractor.is_available:
            logger.debug("Tier 1: Using local embeddings for relation discovery")
            try:
                embedding_suggestions = self.embedding_extractor.extract_relations(
                    hosts,
                    similarity_threshold=0.55,  # Slightly lower to catch more patterns
                    max_relations=100,
                )
                suggestions.extend(embedding_suggestions)
                used_methods.append("embeddings")
                logger.info(f"Embeddings found {len(embedding_suggestions)} relations")
            except Exception as e:
                logger.warning(f"Embedding extraction failed: {e}")

        # ═══════════════════════════════════════════════════════════════
        # TIER 2: LLM (FALLBACK) - Only if embeddings insufficient
        # ═══════════════════════════════════════════════════════════════
        needs_llm = (
            use_llm
            and len(suggestions) < self.MIN_EMBEDDING_RESULTS
            and len(hosts) >= self.MIN_HOSTS_FOR_LLM
        )

        if needs_llm:
            logger.debug(
                f"Tier 2: Embeddings found {len(suggestions)} relations "
                f"(< {self.MIN_EMBEDDING_RESULTS}), trying LLM fallback"
            )
            # Ensure LLM is initialized
            if self.llm and self._llm_extractor:
                try:
                    llm_suggestions = self._llm_extractor.extract_relations(hosts)
                    suggestions.extend(llm_suggestions)
                    used_methods.append("llm")
                    logger.info(f"LLM found {len(llm_suggestions)} additional relations")
                except Exception as e:
                    logger.warning(f"LLM extraction failed: {e}")
            else:
                logger.debug("LLM not available, skipping Tier 2")

        # ═══════════════════════════════════════════════════════════════
        # TIER 3: Heuristics (ALWAYS) - Catch obvious patterns
        # ═══════════════════════════════════════════════════════════════
        logger.debug("Tier 3: Running heuristics for pattern matching")
        heuristic_suggestions = []
        heuristic_suggestions.extend(RelationHeuristics.find_cluster_relations(hosts))
        heuristic_suggestions.extend(RelationHeuristics.find_replica_relations(hosts))
        heuristic_suggestions.extend(RelationHeuristics.find_group_relations(hosts))
        heuristic_suggestions.extend(RelationHeuristics.find_service_relations(hosts))

        if heuristic_suggestions:
            suggestions.extend(heuristic_suggestions)
            used_methods.append("heuristics")
            logger.info(f"Heuristics found {len(heuristic_suggestions)} relations")

        # ═══════════════════════════════════════════════════════════════
        # Post-processing
        # ═══════════════════════════════════════════════════════════════

        # Filter by confidence
        suggestions = [s for s in suggestions if s.confidence >= min_confidence]

        # Remove duplicates (keep highest confidence)
        suggestions = self._deduplicate(suggestions)

        # Filter out existing relations
        if existing_relations:
            suggestions = self._filter_existing(suggestions, existing_relations)

        # Sort by confidence
        suggestions.sort(key=lambda x: x.confidence, reverse=True)

        logger.info(
            f"Total: {len(suggestions)} unique relations "
            f"(methods: {', '.join(used_methods) or 'none'})"
        )

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
