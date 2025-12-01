"""
Relation Classifier Heuristics.
"""

import re
from typing import Dict, List

from .models import RelationSuggestion


class RelationHeuristics:
    """Heuristic rules for detecting host relations."""

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

    @classmethod
    def find_cluster_relations(cls, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Find cluster relations based on naming patterns."""
        suggestions = []
        hostname_groups: Dict[str, List[str]] = {}

        for host in hosts:
            hostname = host.get("hostname", "")

            for pattern in cls.CLUSTER_PATTERNS:
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

    @classmethod
    def find_replica_relations(cls, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Find database replication relations."""
        suggestions = []
        hostnames = {h.get("hostname", ""): h for h in hosts}

        for primary_term, secondary_term in cls.REPLICA_PATTERNS:
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

    @classmethod
    def find_group_relations(cls, hosts: List[Dict]) -> List[RelationSuggestion]:
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

    @classmethod
    def find_service_relations(
        cls,
        hosts: List[Dict],
        max_relations_per_pair: int = 5,
        secondary_threshold: int = 10,
    ) -> List[RelationSuggestion]:
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

            # Skip if no matches on either side
            if not dependents or not dependencies:
                continue

            # Calculate cartesian product size
            cartesian_size = len(dependents) * len(dependencies)

            # Determine confidence: reduce when many hosts exist
            many_hosts = len(dependents) > secondary_threshold or len(dependencies) > secondary_threshold
            base_confidence = 0.3 if many_hosts else 0.5

            if cartesian_size <= max_relations_per_pair:
                # Small enough: create all relations
                for dependent in dependents:
                    for dependency in dependencies:
                        if dependent != dependency:
                            suggestions.append(RelationSuggestion(
                                source_hostname=dependent,
                                target_hostname=dependency,
                                relation_type="depends_on",
                                confidence=base_confidence,
                                reason="Service dependency pattern",
                            ))
            else:
                # Use star topology: connect first dependent to all dependencies
                # This bounds relations to len(dependencies) instead of cartesian product
                hub_dependent = dependents[0]
                relations_created = 0

                for dependency in dependencies:
                    if hub_dependent != dependency and relations_created < max_relations_per_pair:
                        suggestions.append(RelationSuggestion(
                            source_hostname=hub_dependent,
                            target_hostname=dependency,
                            relation_type="depends_on",
                            confidence=base_confidence * 0.9,  # Slightly lower for star topology
                            reason=f"Service dependency pattern (star topology, {len(dependents)} dependents)",
                            metadata={"topology": "star", "total_dependents": len(dependents)},
                        ))
                        relations_created += 1

                # If we have room, also connect first dependency to remaining dependents (round-robin)
                if relations_created < max_relations_per_pair and dependencies:
                    hub_dependency = dependencies[0]
                    for dependent in dependents[1:]:  # Skip first, already used as hub
                        if dependent != hub_dependency and relations_created < max_relations_per_pair:
                            suggestions.append(RelationSuggestion(
                                source_hostname=dependent,
                                target_hostname=hub_dependency,
                                relation_type="depends_on",
                                confidence=base_confidence * 0.9,
                                reason=f"Service dependency pattern (star topology, {len(dependencies)} dependencies)",
                                metadata={"topology": "star", "total_dependencies": len(dependencies)},
                            ))
                            relations_created += 1

        return suggestions
