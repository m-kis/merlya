"""
Lightweight contextual memory system for agent conversations.

Inspired by Zep but simplified for our use case:
- Tracks recently used hosts in the session
- Provides smart context summarization
- Avoids sending large inventory to LLM

This prevents OpenRouter 500 errors from oversized prompts.
"""
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from merlya.memory.persistent_store import KnowledgeStore
from merlya.memory.skill_store import SkillStore
from merlya.utils.logger import logger


class ContextMemory:
    """
    Lightweight memory system that tracks context usage during a session.

    Features:
    - Remembers which hosts were mentioned/used recently
    - Provides compact context summaries
    - Pattern-based host filtering (mongo, prod, mysql, etc.)
    - Access to learned Skills
    """

    def __init__(self, max_hosts_in_context: int = 20):
        """
        Initialize context memory.

        Args:
            max_hosts_in_context: Maximum number of hosts to include in context
        """
        self.max_hosts_in_context = max_hosts_in_context

        # Track hosts used in this session
        self.recently_used_hosts: Set[str] = set()

        # Track query patterns (for semantic matching)
        self.query_patterns: List[str] = []

        # Host usage frequency
        self.host_frequency: Dict[str, int] = defaultdict(int)

        # Persistent knowledge store
        self.knowledge_store = KnowledgeStore()

        # Learned skills store
        self.skill_store = SkillStore()

        # Load initial context from persistence if available
        self._load_from_persistence()

    def extract_host_patterns(self, query: str) -> List[str]:
        """
        Extract host patterns from user query.

        Examples:
        - "check mongo" → ["mongo"]
        - "prod database" → ["prod", "database"]
        - "mongo-preprod-1" → ["mongo-preprod-1"]
        """
        query_lower = query.lower()

        patterns = []

        # Common infrastructure keywords
        keywords = [
            'mongo', 'mysql', 'postgres', 'postgresql', 'redis', 'elastic',
            'prod', 'preprod', 'staging', 'dev',
            'web', 'api', 'lb', 'loadbalancer',
            'db', 'database', 'cache',
            'cluster', 'node'
        ]

        for keyword in keywords:
            if keyword in query_lower:
                patterns.append(keyword)

        # Extract explicit host names (uppercase words with numbers/hyphens)
        host_pattern = r'\b[A-Z][A-Z0-9\-]+\b'
        explicit_hosts = re.findall(host_pattern, query)
        patterns.extend([h.lower() for h in explicit_hosts])

        return patterns

    def filter_relevant_hosts(self,
                             inventory: Dict[str, str],
                             query: Optional[str] = None) -> Dict[str, str]:
        """
        Filter inventory to only include relevant hosts.

        Priority:
        1. Recently used hosts in this session
        2. Hosts matching query patterns
        3. Most frequently used hosts
        4. Sample of remaining hosts

        Args:
            inventory: Full inventory dict {hostname: ip}
            query: Optional user query for pattern extraction

        Returns:
            Filtered inventory with max_hosts_in_context entries
        """
        if len(inventory) <= self.max_hosts_in_context:
            return inventory

        logger.debug(f"Filtering {len(inventory)} hosts to {self.max_hosts_in_context} most relevant")

        relevant: Dict[str, str] = {}
        patterns: List[str] = []

        # Extract patterns from current query
        if query:
            patterns = self.extract_host_patterns(query)
            self.query_patterns.extend(patterns)
            logger.debug(f"Query patterns: {patterns}")

        # Priority 1: Recently used hosts
        for host in self.recently_used_hosts:
            if host in inventory and len(relevant) < self.max_hosts_in_context:
                relevant[host] = inventory[host]

        # Priority 2: Hosts matching query patterns
        if patterns:
            for hostname, ip in inventory.items():
                if len(relevant) >= self.max_hosts_in_context:
                    break

                hostname_lower = hostname.lower()
                if any(pattern in hostname_lower for pattern in patterns):
                    if hostname not in relevant:
                        relevant[hostname] = ip

        # Priority 3: Most frequently used hosts
        sorted_by_freq = sorted(
            self.host_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )

        for hostname, _ in sorted_by_freq:
            if len(relevant) >= self.max_hosts_in_context:
                break
            if hostname in inventory and hostname not in relevant:
                relevant[hostname] = inventory[hostname]

        # Priority 4: Fill with diverse sample (different patterns)
        if len(relevant) < self.max_hosts_in_context:
            # Get hosts with common patterns (mongo, mysql, prod, etc.)
            diverse_patterns = ['mongo', 'mysql', 'postgres', 'prod', 'web', 'api']

            for pattern in diverse_patterns:
                for hostname, ip in inventory.items():
                    if len(relevant) >= self.max_hosts_in_context:
                        break
                    if pattern in hostname.lower() and hostname not in relevant:
                        relevant[hostname] = ip

        # Final fill: just take first available
        for hostname, ip in list(inventory.items())[:self.max_hosts_in_context]:
            if len(relevant) >= self.max_hosts_in_context:
                break
            if hostname not in relevant:
                relevant[hostname] = ip

        omitted = len(inventory) - len(relevant)
        logger.info(f"Context memory: showing {len(relevant)} hosts, {omitted} omitted (use get_infrastructure_context tool for full list)")

        return relevant

    def record_host_usage(self, hostname: str):
        """Record that a host was used (mentioned or accessed)."""
        self.recently_used_hosts.add(hostname)
        self.host_frequency[hostname] += 1
        logger.debug(f"Context memory: recorded usage of {hostname} (freq: {self.host_frequency[hostname]})")

    def get_context_summary(self, inventory: Dict[str, str]) -> str:
        """
        Get a compact summary of the infrastructure context.

        Returns:
            Formatted summary string
        """
        total_hosts = len(inventory)

        # Count by pattern
        counts = {
            'mongo': 0,
            'mysql': 0,
            'postgres': 0,
            'redis': 0,
            'prod': 0,
            'preprod': 0,
            'web': 0
        }

        for hostname in inventory.keys():
            hostname_lower = hostname.lower()
            for pattern in counts:
                if pattern in hostname_lower:
                    counts[pattern] += 1

        summary_lines = [
            f"Total hosts: {total_hosts}",
        ]

        # Add counts for non-zero patterns
        pattern_summary = []
        for pattern, count in counts.items():
            if count > 0:
                pattern_summary.append(f"{count} {pattern}")

        if pattern_summary:
            summary_lines.append(f"Breakdown: {', '.join(pattern_summary)}")

        return " | ".join(summary_lines)

    def clear_session(self):
        """Clear session-specific memory (keeps frequency data)."""
        self.recently_used_hosts.clear()
        self.query_patterns.clear()
        logger.debug("Context memory: session cleared")

    def _load_from_persistence(self):
        """Load frequently used hosts from persistent store."""
        # This is a simple implementation - in future we could load based on time/relevance
        try:
            hosts = self.knowledge_store.data.get("hosts", {})
            # Pre-populate frequency for known hosts to give them slight boost
            for hostname in hosts:
                self.host_frequency[hostname] += 1
        except Exception as e:
            logger.warning(f"Failed to load from persistence: {e}")

    def save_host_fact(self, hostname: str, category: str, value: Any):
        """Save a learned fact to persistent storage."""
        self.knowledge_store.update_host_fact(hostname, category, value)

