"""
Host Relation Classifier - AI-assisted relation discovery.

Suggests relations between hosts based on:
- Naming patterns
- Groups/environments
- Services detected
- Metadata

Uses the same LLM as intent/triage (Ollama local by default).
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


@dataclass
class RelationSuggestion:
    """A suggested relation between two hosts."""

    source_hostname: str
    target_hostname: str
    relation_type: str
    confidence: float
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_hostname": self.source_hostname,
            "target_hostname": self.target_hostname,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "metadata": self.metadata,
        }


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

    RELATION_TYPES = [
        "cluster_member",
        "database_replica",
        "depends_on",
        "backup_of",
        "load_balanced",
        "related_service",
    ]

    # Patterns for detecting relations
    CLUSTER_PATTERNS = [
        r"^(.+)-(\d+)$",           # web-01, web-02
        r"^(.+)(\d+)$",            # web1, web2
        r"^(.+)-node(\d+)$",       # cluster-node1
        r"^(.+)-server(\d+)$",     # app-server1
    ]

    REPLICA_PATTERNS = [
        ("master", "slave"),
        ("master", "replica"),
        ("primary", "secondary"),
        ("primary", "replica"),
        ("leader", "follower"),
        ("main", "backup"),
    ]

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
        suggestions.extend(self._heuristic_cluster_relations(hosts))
        suggestions.extend(self._heuristic_replica_relations(hosts))
        suggestions.extend(self._heuristic_group_relations(hosts))
        suggestions.extend(self._heuristic_service_relations(hosts))

        # 2. LLM-based relations (if few heuristic results)
        if use_llm and len(suggestions) < 5 and len(hosts) > 2:
            llm_suggestions = self._llm_relations(hosts)
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

    def _heuristic_cluster_relations(self, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Find cluster relations based on naming patterns."""
        suggestions = []
        hostname_groups: Dict[str, List[str]] = {}

        for host in hosts:
            hostname = host.get("hostname", "")

            for pattern in self.CLUSTER_PATTERNS:
                match = re.match(pattern, hostname)
                if match:
                    base_name = match.group(1)
                    if base_name not in hostname_groups:
                        hostname_groups[base_name] = []
                    hostname_groups[base_name].append(hostname)
                    break

        # Create relations for groups with multiple hosts
        # Use star topology for large clusters to avoid O(n²) explosion
        max_pairwise = 20  # Switch to star topology above this size
        for base_name, group_hosts in hostname_groups.items():
            if len(group_hosts) < 2:
                continue

            if len(group_hosts) <= max_pairwise:
                # Small cluster: create pairwise relations
                for i, host1 in enumerate(group_hosts):
                    for host2 in group_hosts[i + 1:]:
                        suggestions.append(RelationSuggestion(
                            source_hostname=host1,
                            target_hostname=host2,
                            relation_type="cluster_member",
                            confidence=0.85,
                            reason=f"Same naming pattern: {base_name}-*",
                        ))
            else:
                # Large cluster: use star topology (first host as hub)
                hub = group_hosts[0]
                for member in group_hosts[1:]:
                    suggestions.append(RelationSuggestion(
                        source_hostname=hub,
                        target_hostname=member,
                        relation_type="cluster_member",
                        confidence=0.8,  # Slightly lower confidence for star topology
                        reason=f"Same naming pattern: {base_name}-* (star topology, {len(group_hosts)} members)",
                    ))

        return suggestions

    def _heuristic_replica_relations(self, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Find database replication relations."""
        suggestions = []
        hostnames = {h.get("hostname", ""): h for h in hosts}

        for primary_term, secondary_term in self.REPLICA_PATTERNS:
            for hostname in hostnames:
                # Check if hostname contains primary term
                if primary_term in hostname.lower():
                    # Look for corresponding replica (replace only first occurrence)
                    potential_replica = hostname.lower().replace(primary_term, secondary_term, 1)

                    for other_hostname in hostnames:
                        if other_hostname.lower() == potential_replica:
                            suggestions.append(RelationSuggestion(
                                source_hostname=other_hostname,
                                target_hostname=hostname,
                                relation_type="database_replica",
                                confidence=0.9,
                                reason=f"Naming pattern: {primary_term}/{secondary_term}",
                            ))

        return suggestions

    def _heuristic_group_relations(self, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Find relations based on shared groups."""
        suggestions = []
        group_hosts: Dict[str, List[str]] = {}

        for host in hosts:
            hostname = host.get("hostname", "")
            groups = host.get("groups", [])

            for group in groups:
                if group not in group_hosts:
                    group_hosts[group] = []
                group_hosts[group].append(hostname)

        # Create relations for hosts in same group
        # Use star topology for large groups to avoid O(n²) explosion
        max_pairwise = 20  # Switch to star topology above this size
        for group, group_members in group_hosts.items():
            if len(group_members) < 2:
                continue

            # Skip generic groups
            if group.lower() in ["all", "ungrouped", "servers", "hosts"]:
                continue

            if len(group_members) <= max_pairwise:
                # Small group: create pairwise relations
                for i, host1 in enumerate(group_members):
                    for host2 in group_members[i + 1:]:
                        suggestions.append(RelationSuggestion(
                            source_hostname=host1,
                            target_hostname=host2,
                            relation_type="related_service",
                            confidence=0.6,
                            reason=f"Same group: {group}",
                            metadata={"group": group},
                        ))
            else:
                # Large group: use star topology (first host as hub)
                hub = group_members[0]
                for member in group_members[1:]:
                    suggestions.append(RelationSuggestion(
                        source_hostname=hub,
                        target_hostname=member,
                        relation_type="related_service",
                        confidence=0.55,  # Slightly lower confidence for star topology
                        reason=f"Same group: {group} (star topology, {len(group_members)} members)",
                        metadata={"group": group},
                    ))

        return suggestions

    def _heuristic_service_relations(self, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Find relations based on service types in hostnames."""
        suggestions = []

        # Common service patterns that typically have dependencies
        service_dependencies = [
            (["web", "frontend", "ui"], ["api", "backend", "app"]),
            (["api", "backend", "app"], ["db", "database", "mysql", "postgres", "mongo"]),
            (["app", "backend"], ["cache", "redis", "memcached"]),
            (["app", "backend"], ["queue", "rabbitmq", "kafka"]),
        ]

        hostnames = [h.get("hostname", "") for h in hosts]

        for dependent_terms, dependency_terms in service_dependencies:
            dependents = [h for h in hostnames
                          if any(term in h.lower() for term in dependent_terms)]
            dependencies = [h for h in hostnames
                            if any(term in h.lower() for term in dependency_terms)]

            for dependent in dependents:
                for dependency in dependencies:
                    if dependent != dependency:
                        suggestions.append(RelationSuggestion(
                            source_hostname=dependent,
                            target_hostname=dependency,
                            relation_type="depends_on",
                            confidence=0.5,
                            reason=f"Service dependency pattern",
                        ))

        return suggestions

    def _llm_relations(self, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Use LLM to discover complex relations."""
        suggestions = []

        if not self.llm:
            return suggestions

        # Build map of lowercase -> original hostname for preserving casing
        original_hostnames: Dict[str, str] = {}
        for host in hosts:
            hostname = host.get("hostname", "")
            if hostname:
                original_hostnames[hostname.lower()] = hostname

        # Prepare host summary for LLM
        host_summary = []
        for host in hosts[:50]:  # Limit to 50 hosts
            entry = host.get("hostname", "")
            if host.get("environment"):
                entry += f" (env: {host['environment']})"
            if host.get("groups"):
                entry += f" (groups: {', '.join(host['groups'][:3])})"
            if host.get("service"):
                entry += f" (service: {host['service']})"
            host_summary.append(entry)

        prompt = f"""Analyze these server hostnames and suggest relationships between them.

Hostnames:
{chr(10).join(host_summary)}

For each relationship, identify:
1. Source hostname
2. Target hostname
3. Relationship type: cluster_member, database_replica, depends_on, backup_of, load_balanced, related_service
4. Confidence (0.5-1.0)
5. Reason

Return ONLY a JSON array with objects containing: source, target, type, confidence, reason

Example:
[{{"source": "web-01", "target": "web-02", "type": "cluster_member", "confidence": 0.8, "reason": "Same naming pattern"}}]

Return ONLY valid JSON, no explanations. Return empty array [] if no clear relationships found."""

        try:
            response = self.llm.generate(prompt, task="synthesis")

            # Extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                for item in data:
                    if isinstance(item, dict) and item.get("source") and item.get("target"):
                        # Validate relation_type against allowed types
                        relation_type = item.get("type", "related_service")
                        if relation_type not in self.RELATION_TYPES:
                            logger.debug(f"Invalid relation type from LLM: {relation_type}, defaulting to related_service")
                            relation_type = "related_service"
                        # Preserve original hostname casing using the map
                        source = item["source"]
                        target = item["target"]
                        source_hostname = original_hostnames.get(source.lower(), source)
                        target_hostname = original_hostnames.get(target.lower(), target)
                        suggestions.append(RelationSuggestion(
                            source_hostname=source_hostname,
                            target_hostname=target_hostname,
                            relation_type=relation_type,
                            confidence=min(float(item.get("confidence", 0.5)), 0.75),  # Cap LLM confidence
                            reason=item.get("reason", "LLM suggestion"),
                            metadata={"source": "llm"},
                        ))

        except Exception as e:
            logger.debug(f"LLM relation discovery failed: {e}")

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


# Singleton
_classifier: Optional[HostRelationClassifier] = None


def get_relation_classifier() -> HostRelationClassifier:
    """Get the relation classifier singleton."""
    global _classifier
    if _classifier is None:
        _classifier = HostRelationClassifier()
    return _classifier
