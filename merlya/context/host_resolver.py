"""
Host Resolver - Intelligent hostname resolution with disambiguation.

Solves the problem where similar hostnames (e.g., ANSIBLE vs ANSIBLEDEVOPS)
are confused by providing:
1. Exact match priority
2. Partial match disambiguation
3. Interactive disambiguation when multiple candidates exist
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from merlya.context.host_registry import HostRegistry, get_host_registry
from merlya.context.sources.base import Host


@dataclass
class ResolvedHost:
    """Result of hostname resolution."""
    host: Optional[Host]
    exact_match: bool
    confidence: float
    alternatives: List[Tuple[str, float]]  # (hostname, similarity_score)
    disambiguation_needed: bool
    error_message: Optional[str] = None


class HostResolver:
    """
    Intelligent host resolver with disambiguation support.

    Prioritizes:
    1. Exact matches (case-insensitive)
    2. Alias matches
    3. Partial matches with disambiguation
    """

    # Minimum similarity for a match to be considered
    MIN_SIMILARITY = 0.4

    # Threshold above which we consider it a confident match
    CONFIDENT_MATCH = 0.85

    # Maximum number of alternatives to show
    MAX_ALTERNATIVES = 5

    def __init__(self, registry: Optional[HostRegistry] = None):
        self.registry = registry or get_host_registry()

    def resolve(self, query: str, context: Optional[str] = None) -> ResolvedHost:
        """
        Resolve a hostname query to a host.

        Args:
            query: Hostname query (can be partial)
            context: Optional context to help disambiguation (e.g., "ansible", "prod")

        Returns:
            ResolvedHost with resolution result
        """
        if not query:
            return ResolvedHost(
                host=None,
                exact_match=False,
                confidence=0.0,
                alternatives=[],
                disambiguation_needed=False,
                error_message="Empty hostname query"
            )

        # Ensure registry is loaded
        if self.registry.is_empty():
            self.registry.load_all_sources()

        query_lower = query.lower().strip()

        # 1. Try exact match first
        exact_host = self._find_exact_match(query_lower)
        if exact_host:
            return ResolvedHost(
                host=exact_host,
                exact_match=True,
                confidence=1.0,
                alternatives=[],
                disambiguation_needed=False
            )

        # 2. Find all candidates with similarity scores
        candidates = self._find_candidates(query_lower, context)

        if not candidates:
            # No matches found
            return ResolvedHost(
                host=None,
                exact_match=False,
                confidence=0.0,
                alternatives=[],
                disambiguation_needed=False,
                error_message=f"No hosts found matching '{query}'"
            )

        # 3. Check if we have a single high-confidence match
        best_match = candidates[0]
        best_hostname, best_score = best_match

        # If best match is very confident and significantly better than second
        if best_score >= self.CONFIDENT_MATCH:
            second_best_score = candidates[1][1] if len(candidates) > 1 else 0
            if best_score - second_best_score >= 0.15:  # Significant gap
                host = self.registry.get(best_hostname)
                return ResolvedHost(
                    host=host,
                    exact_match=False,
                    confidence=best_score,
                    alternatives=candidates[1:self.MAX_ALTERNATIVES],
                    disambiguation_needed=False
                )

        # 4. Check for ambiguous matches - need disambiguation
        # Find how many candidates are within 0.1 of the best score
        close_candidates = [c for c in candidates if best_score - c[1] <= 0.1]

        if len(close_candidates) > 1:
            # Multiple close matches - need disambiguation
            return ResolvedHost(
                host=None,
                exact_match=False,
                confidence=best_score,
                alternatives=candidates[:self.MAX_ALTERNATIVES],
                disambiguation_needed=True,
                error_message=f"Multiple hosts match '{query}'. Please specify which one."
            )

        # Single best match with reasonable confidence
        host = self.registry.get(best_hostname)
        return ResolvedHost(
            host=host,
            exact_match=False,
            confidence=best_score,
            alternatives=candidates[1:self.MAX_ALTERNATIVES],
            disambiguation_needed=False
        )

    def _find_exact_match(self, query: str) -> Optional[Host]:
        """Find exact match (case-insensitive) in registry."""
        # Check direct hostname match
        for hostname, host in self.registry.hosts.items():
            if hostname.lower() == query:
                return host
            # Check aliases
            for alias in host.aliases:
                if alias.lower() == query:
                    return host
        return None

    def _find_candidates(
        self,
        query: str,
        context: Optional[str] = None
    ) -> List[Tuple[str, float]]:
        """
        Find candidate hosts with similarity scores.

        Uses multiple matching strategies:
        1. Substring containment (exact query in hostname)
        2. Sequence matching (SequenceMatcher)
        3. Context boosting (if context matches environment/group)
        """
        candidates = []
        context_lower = context.lower() if context else None

        for hostname, host in self.registry.hosts.items():
            hostname_lower = hostname.lower()

            # Calculate base similarity score
            score = 0.0

            # Strategy 1: Exact substring match gets high score
            if query in hostname_lower:
                # Score based on how much of the hostname the query covers
                coverage = len(query) / len(hostname_lower)
                score = max(score, 0.6 + (coverage * 0.3))  # 0.6-0.9 range

            if hostname_lower in query:
                # Hostname is substring of query
                coverage = len(hostname_lower) / len(query)
                score = max(score, 0.5 + (coverage * 0.3))

            # Strategy 2: Sequence matching
            seq_score = SequenceMatcher(None, query, hostname_lower).ratio()
            score = max(score, seq_score)

            # Strategy 3: Context boosting
            if context_lower and score >= self.MIN_SIMILARITY:
                # Boost if context matches environment or groups
                env = (host.environment or "").lower()
                groups = [g.lower() for g in host.groups]

                if context_lower in env or context_lower in " ".join(groups):
                    score = min(score + 0.1, 1.0)

            # Only include if above threshold
            if score >= self.MIN_SIMILARITY:
                candidates.append((hostname, score))

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def format_disambiguation(self, result: ResolvedHost, query: str) -> str:
        """
        Format a disambiguation message for the user.

        Args:
            result: ResolvedHost with alternatives
            query: Original query

        Returns:
            Formatted message with numbered options
        """
        if not result.alternatives and not result.disambiguation_needed:
            if result.error_message:
                return result.error_message
            return f"No hosts found matching '{query}'"

        lines = [f"Multiple hosts match '{query}':", ""]

        all_options = []
        if result.host:
            all_options.append((result.host.hostname, result.confidence))
        all_options.extend(result.alternatives)

        for i, (hostname, score) in enumerate(all_options, 1):
            host = self.registry.get(hostname)
            env_info = f" [{host.environment}]" if host and host.environment else ""
            ip_info = f" ({host.ip_address})" if host and host.ip_address else ""
            score_pct = int(score * 100)
            lines.append(f"  {i}. {hostname}{ip_info}{env_info} ({score_pct}% match)")

        lines.append("")
        lines.append("Please specify the exact hostname you want to use.")

        return "\n".join(lines)


# Singleton instance
_resolver: Optional[HostResolver] = None


def get_host_resolver(registry: Optional[HostRegistry] = None) -> HostResolver:
    """Get the global HostResolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = HostResolver(registry)
    return _resolver


def reset_host_resolver() -> None:
    """Reset the global resolver (for testing)."""
    global _resolver
    _resolver = None


def resolve_hostname(query: str, context: Optional[str] = None) -> ResolvedHost:
    """
    Convenience function to resolve a hostname.

    Args:
        query: Hostname query
        context: Optional context for disambiguation

    Returns:
        ResolvedHost result
    """
    return get_host_resolver().resolve(query, context)
