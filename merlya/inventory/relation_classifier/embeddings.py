"""
Embedding-based Relation Extractor.

Uses local sentence-transformers model for semantic similarity
between hostnames to discover relationships.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from merlya.utils.logger import logger

from .models import RelationSuggestion

# Optional imports for embeddings
try:
    import numpy as np

    from merlya.triage.smart_classifier.embedding_cache import (
        HAS_EMBEDDINGS,
        EmbeddingCache,
    )
except ImportError:
    HAS_EMBEDDINGS = False
    np = None  # type: ignore
    EmbeddingCache = None  # type: ignore


class EmbeddingRelationExtractor:
    """
    Embedding-based relation discovery using local sentence-transformers.

    Uses semantic similarity between hostname components to find:
    - Cluster members (similar base names)
    - Service relationships (similar service types)
    - Environment groupings (similar env patterns)

    This is the PRIMARY method for relation discovery as it:
    - Runs locally (no API calls)
    - Fast inference
    - Works offline
    - Privacy-preserving
    """

    # Relation type reference patterns for semantic matching
    RELATION_PATTERNS: Dict[str, List[str]] = {
        "cluster_member": [
            "same cluster group",
            "identical service instances",
            "load balanced servers",
            "replicated nodes",
            "horizontal scaling",
        ],
        "database_replica": [
            "database replication",
            "master slave database",
            "primary secondary replica",
            "data synchronization",
            "database cluster",
        ],
        "depends_on": [
            "service dependency",
            "requires backend",
            "connects to database",
            "uses cache service",
            "calls api endpoint",
        ],
        "backup_of": [
            "backup server",
            "disaster recovery",
            "standby system",
            "failover target",
            "redundant copy",
        ],
        "load_balanced": [
            "load balancer pool",
            "traffic distribution",
            "round robin servers",
            "backend pool members",
            "upstream servers",
        ],
        "related_service": [
            "related infrastructure",
            "same application stack",
            "shared environment",
            "common project",
            "service group",
        ],
    }

    # Common hostname components to expand for better semantic matching
    HOSTNAME_EXPANSIONS: Dict[str, str] = {
        "db": "database server",
        "web": "web frontend server",
        "api": "api backend server",
        "app": "application server",
        "cache": "cache server redis memcached",
        "redis": "redis cache server",
        "mongo": "mongodb database server",
        "mysql": "mysql database server",
        "postgres": "postgresql database server",
        "pg": "postgresql database server",
        "es": "elasticsearch search server",
        "elastic": "elasticsearch search server",
        "kafka": "kafka message queue server",
        "rabbit": "rabbitmq message queue server",
        "mq": "message queue server",
        "lb": "load balancer server",
        "proxy": "proxy reverse proxy server",
        "nginx": "nginx web proxy server",
        "haproxy": "haproxy load balancer",
        "k8s": "kubernetes cluster node",
        "kube": "kubernetes cluster node",
        "node": "cluster node worker",
        "master": "master primary leader server",
        "slave": "slave secondary follower server",
        "replica": "replica secondary follower server",
        "primary": "primary master leader server",
        "secondary": "secondary slave follower server",
        "prod": "production environment",
        "staging": "staging environment",
        "dev": "development environment",
        "preprod": "preproduction staging environment",
        "test": "testing environment",
    }

    def __init__(self, embedding_cache: Optional["EmbeddingCache"] = None):
        """Initialize with optional embedding cache.

        Args:
            embedding_cache: Shared EmbeddingCache instance. If None, creates own.
        """
        self._cache = embedding_cache
        self._relation_embeddings: Optional[Dict[str, Any]] = None

    @property
    def is_available(self) -> bool:
        """Check if embeddings are available."""
        return HAS_EMBEDDINGS

    @property
    def cache(self) -> Optional["EmbeddingCache"]:
        """Lazy load embedding cache."""
        if not HAS_EMBEDDINGS:
            return None
        if self._cache is None:
            self._cache = EmbeddingCache()
        return self._cache

    def _get_relation_embeddings(self) -> Dict[str, Any]:
        """Get cached embeddings for relation type patterns."""
        if self._relation_embeddings is not None:
            return self._relation_embeddings

        if not self.cache:
            return {}

        self._relation_embeddings = {}
        for rel_type, patterns in self.RELATION_PATTERNS.items():
            embeddings = self.cache.get_embeddings_batch(patterns)
            self._relation_embeddings[rel_type] = np.array(embeddings)

        return self._relation_embeddings

    def _expand_hostname(self, hostname: str) -> str:
        """Expand hostname into semantic description.

        Transforms 'web-prod-01' into 'web frontend server production environment instance 01'
        """
        # Split hostname into components
        parts = re.split(r"[-_.]", hostname.lower())
        expanded_parts = []

        for part in parts:
            # Remove digits for expansion lookup
            base = re.sub(r"\d+$", "", part)

            if base in self.HOSTNAME_EXPANSIONS:
                expanded_parts.append(self.HOSTNAME_EXPANSIONS[base])
            else:
                expanded_parts.append(part)

            # Keep the number suffix if present
            num_match = re.search(r"(\d+)$", part)
            if num_match:
                expanded_parts.append(f"instance {num_match.group(1)}")

        return " ".join(expanded_parts)

    def _compute_similarity(
        self, embedding1: "np.ndarray", embedding2: "np.ndarray"
    ) -> float:
        """Compute cosine similarity between two embeddings."""
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(np.dot(embedding1, embedding2) / (norm1 * norm2))

    def _infer_relation_type(
        self,
        host1_embedding: "np.ndarray",
        host2_embedding: "np.ndarray",
        host1: str,
        host2: str,
    ) -> Tuple[str, float]:
        """Infer the most likely relation type between two hosts.

        Returns:
            (relation_type, confidence)
        """
        # Combine host embeddings to represent the relationship
        # Using average of embeddings as relationship vector
        relationship_vector = (host1_embedding + host2_embedding) / 2

        relation_embeddings = self._get_relation_embeddings()
        if not relation_embeddings:
            return "related_service", 0.5

        best_type = "related_service"
        best_score = 0.0

        for rel_type, type_embeddings in relation_embeddings.items():
            # Compute max similarity to any reference pattern
            similarities = []
            for ref_emb in type_embeddings:
                sim = self._compute_similarity(relationship_vector, ref_emb)
                similarities.append(sim)

            max_sim = max(similarities) if similarities else 0.0

            if max_sim > best_score:
                best_score = max_sim
                best_type = rel_type

        # Apply heuristic boosts based on hostname patterns
        h1_lower, h2_lower = host1.lower(), host2.lower()

        # Boost cluster_member for numbered hosts
        if re.search(r"\d+$", h1_lower) and re.search(r"\d+$", h2_lower):
            base1 = re.sub(r"\d+$", "", h1_lower)
            base2 = re.sub(r"\d+$", "", h2_lower)
            if base1 == base2:
                if best_type == "cluster_member":
                    best_score = min(best_score + 0.2, 0.95)

        # Boost database_replica for master/slave patterns
        replica_terms = {"master", "slave", "primary", "secondary", "replica"}
        if any(t in h1_lower for t in replica_terms) or any(t in h2_lower for t in replica_terms):
            if best_type == "database_replica":
                best_score = min(best_score + 0.15, 0.95)

        return best_type, best_score

    def extract_relations(
        self,
        hosts: List[Dict[str, Any]],
        similarity_threshold: float = 0.6,
        max_relations: int = 50,
    ) -> List[RelationSuggestion]:
        """Extract relations using semantic similarity.

        Args:
            hosts: List of host dictionaries with 'hostname' key
            similarity_threshold: Minimum similarity to consider (0-1)
            max_relations: Maximum relations to return

        Returns:
            List of RelationSuggestion sorted by confidence
        """
        if not self.is_available or not self.cache:
            logger.debug("Embeddings not available, skipping embedding extraction")
            return []

        if len(hosts) < 2:
            return []

        suggestions: List[RelationSuggestion] = []

        # Extract hostnames and create expanded versions
        hostnames = [h.get("hostname", "") for h in hosts if h.get("hostname")]
        if len(hostnames) < 2:
            return []

        # Limit to prevent explosion
        hostnames = hostnames[:100]

        # Expand hostnames for semantic matching
        expanded = [self._expand_hostname(h) for h in hostnames]

        # Get embeddings for expanded hostnames
        try:
            embeddings = self.cache.get_embeddings_batch(expanded)
            embeddings_array = np.array(embeddings)
        except Exception as e:
            logger.warning(f"Failed to compute embeddings: {e}")
            return []

        # Build host metadata map for additional context
        host_meta: Dict[str, Dict] = {}
        for h in hosts:
            hostname = h.get("hostname", "")
            if hostname:
                host_meta[hostname] = {
                    "environment": h.get("environment"),
                    "groups": h.get("groups", []),
                }

        # Compute pairwise similarities
        seen_pairs: Set[Tuple[str, str]] = set()

        for i, host1 in enumerate(hostnames):
            for j, host2 in enumerate(hostnames):
                if i >= j:  # Skip self and duplicate pairs
                    continue

                # Normalize pair order for deduplication
                pair = tuple(sorted([host1, host2]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Compute similarity
                similarity = self._compute_similarity(
                    embeddings_array[i], embeddings_array[j]
                )

                if similarity < similarity_threshold:
                    continue

                # Infer relation type
                rel_type, type_confidence = self._infer_relation_type(
                    embeddings_array[i],
                    embeddings_array[j],
                    host1,
                    host2,
                )

                # Combine similarity and type confidence
                # Weight: 60% semantic similarity, 40% type match
                final_confidence = 0.6 * similarity + 0.4 * type_confidence

                # Cap at 0.85 for embedding-based (leave room for heuristics)
                final_confidence = min(final_confidence, 0.85)

                # Generate reason
                reason = self._generate_reason(
                    host1, host2, rel_type, similarity, host_meta
                )

                suggestions.append(
                    RelationSuggestion(
                        source_hostname=host1,
                        target_hostname=host2,
                        relation_type=rel_type,
                        confidence=final_confidence,
                        reason=reason,
                        metadata={
                            "source": "embeddings",
                            "similarity": round(similarity, 3),
                            "type_confidence": round(type_confidence, 3),
                        },
                    )
                )

        # Sort by confidence and limit
        suggestions.sort(key=lambda x: x.confidence, reverse=True)
        return suggestions[:max_relations]

    def _generate_reason(
        self,
        host1: str,
        host2: str,
        rel_type: str,
        similarity: float,
        host_meta: Dict[str, Dict],
    ) -> str:
        """Generate human-readable reason for the relation."""
        reasons = []

        # Similarity-based reason
        if similarity > 0.8:
            reasons.append("Very similar hostnames")
        elif similarity > 0.7:
            reasons.append("Similar naming pattern")
        else:
            reasons.append("Related naming structure")

        # Environment match
        env1 = host_meta.get(host1, {}).get("environment")
        env2 = host_meta.get(host2, {}).get("environment")
        if env1 and env2 and env1 == env2:
            reasons.append(f"same env ({env1})")

        # Group overlap
        groups1 = set(host_meta.get(host1, {}).get("groups", []))
        groups2 = set(host_meta.get(host2, {}).get("groups", []))
        common_groups = groups1 & groups2
        if common_groups:
            reasons.append(f"shared groups: {', '.join(list(common_groups)[:2])}")

        # Type-specific context
        type_contexts = {
            "cluster_member": "likely cluster peers",
            "database_replica": "database replication pattern",
            "depends_on": "service dependency detected",
            "load_balanced": "load balancer pool members",
            "backup_of": "backup/failover relationship",
        }
        if rel_type in type_contexts:
            reasons.append(type_contexts[rel_type])

        return "; ".join(reasons[:3])
