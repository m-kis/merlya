"""
Host Registry - Single Source of Truth for Valid Hosts.

This module provides a STRICT host registry that:
1. Only allows operations on hosts that exist in REAL inventory sources
2. NEVER accepts hallucinated/invented hostnames
3. Provides fuzzy matching and suggestions for invalid hostnames
4. Loads from multiple real sources (Ansible, SSH config, /etc/hosts, cloud APIs)

CRITICAL: This is a security-critical module. Never execute commands on unvalidated hosts.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from merlya.context.sources.ansible import AnsibleSource
from merlya.context.sources.base import Host, HostValidationResult, InventorySource
from merlya.context.sources.cloud import AWSSource, GCPSource
from merlya.context.sources.local import EtcHostsSource, SSHConfigSource
from merlya.context.sources.sqlite import SQLiteSource
from merlya.utils.logger import logger


class HostRegistry:
    """
    Single source of truth for valid hosts.

    CRITICAL: Only hosts registered here are valid targets for operations.
    This prevents LLM hallucination attacks where fake hostnames are executed.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the host registry.

        Args:
            config: Configuration with inventory sources
        """
        self.config = config or {}
        self._hosts: Dict[str, Host] = {}  # hostname -> Host
        self._aliases: Dict[str, str] = {}  # alias -> canonical hostname
        self._loaded_sources: Set[InventorySource] = set()
        self._last_refresh: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=self.config.get("cache_ttl_minutes", 15))

    @property
    def hosts(self) -> Dict[str, Host]:
        """Get all registered hosts."""
        return self._hosts.copy()

    @property
    def hostnames(self) -> List[str]:
        """Get list of all valid hostnames."""
        return list(self._hosts.keys())

    def is_empty(self) -> bool:
        """Check if registry has no hosts."""
        return len(self._hosts) == 0

    def load_all_sources(self, force_refresh: bool = False) -> int:
        """
        Load hosts from all configured sources.

        Args:
            force_refresh: Force reload even if cache is valid

        Returns:
            Number of hosts loaded
        """
        # Check cache validity
        if not force_refresh and self._last_refresh:
            if datetime.now() - self._last_refresh < self._cache_ttl:
                logger.debug("Host registry cache still valid, skipping reload")
                return len(self._hosts)

        # Initialize sources
        # SQLite source first - contains manually added hosts via /inventory add
        sources = [
            SQLiteSource(self.config),
            EtcHostsSource(self.config),
            SSHConfigSource(self.config),
            AnsibleSource(self.config),
        ]

        if self.config.get("enable_aws"):
            sources.append(AWSSource(self.config))
        if self.config.get("enable_gcp"):
            sources.append(GCPSource(self.config))

        # Load from each source
        for source in sources:
            hosts = source.load()
            for host in hosts:
                self._register_host(host)
                self._loaded_sources.add(host.source)

        self._last_refresh = datetime.now()

        logger.info(f"Host registry loaded: {len(self._hosts)} total hosts from {len(self._loaded_sources)} sources")
        return len(self._hosts)

    def _register_host(self, host: Host) -> None:
        """Register a host in the registry."""
        hostname_lower = host.hostname.lower()

        # Merge if already exists
        if hostname_lower in self._hosts:
            existing = self._hosts[hostname_lower]
            # Merge aliases
            existing.aliases = list(set(existing.aliases + host.aliases))
            # Update IP if not set
            if not existing.ip_address and host.ip_address:
                existing.ip_address = host.ip_address
            # Merge groups
            existing.groups = list(set(existing.groups + host.groups))
            # Merge metadata
            existing.metadata.update(host.metadata)
        else:
            self._hosts[hostname_lower] = host

        # Register aliases
        for alias in host.aliases:
            self._aliases[alias.lower()] = hostname_lower

    def register_manual_host(
        self,
        hostname: str,
        ip_address: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> Host:
        """
        Manually register a host (e.g., from user confirmation).

        Args:
            hostname: Hostname to register
            ip_address: Optional IP address
            environment: Optional environment (prod, staging, dev)

        Returns:
            Registered Host object
        """
        host = Host(
            hostname=hostname,
            ip_address=ip_address,
            source=InventorySource.MANUAL,
            environment=environment,
            last_seen=datetime.now(),
        )
        self._register_host(host)
        logger.info(f"Manually registered host: {hostname}")
        return host

    def validate(self, hostname: str) -> HostValidationResult:
        """
        Validate if a hostname exists in the registry.

        This is the CRITICAL security function that prevents hallucination attacks.

        Args:
            hostname: Hostname to validate

        Returns:
            HostValidationResult with validity status and suggestions
        """
        if not hostname:
            return HostValidationResult(
                is_valid=False,
                original_query=hostname or "",
                error_message="Empty hostname provided",
            )

        # Ensure registry is loaded
        if self.is_empty():
            self.load_all_sources()

        hostname_lower = hostname.lower()

        # Direct match
        if hostname_lower in self._hosts:
            return HostValidationResult(
                is_valid=True,
                host=self._hosts[hostname_lower],
                original_query=hostname,
            )

        # Alias match
        if hostname_lower in self._aliases:
            canonical = self._aliases[hostname_lower]
            return HostValidationResult(
                is_valid=True,
                host=self._hosts[canonical],
                original_query=hostname,
            )

        # Not found - find suggestions
        suggestions = self._find_similar(hostname)

        return HostValidationResult(
            is_valid=False,
            original_query=hostname,
            suggestions=suggestions,
            error_message=f"Host '{hostname}' not found in inventory",
        )

    def _find_similar(self, query: str, max_results: int = 5) -> List[Tuple[str, float]]:
        """Find similar hostnames using fuzzy matching."""
        matches = []

        for _hostname, host in self._hosts.items():
            score = host.similarity(query)
            if score > 0.4:  # Minimum similarity threshold
                matches.append((host.hostname, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:max_results]

    def get(self, hostname: str) -> Optional[Host]:
        """
        Get a host by name (returns None if not found).

        Use validate() for security-critical operations.
        """
        result = self.validate(hostname)
        return result.host if result.is_valid else None

    def require(self, hostname: str) -> Host:
        """
        Get a host by name (raises if not found).

        Use this for strict validation in security-critical paths.

        Raises:
            ValueError: If host not found
        """
        result = self.validate(hostname)
        if not result.is_valid or result.host is None:
            raise ValueError(result.get_suggestion_text())
        return result.host

    def filter(
        self,
        environment: Optional[str] = None,
        group: Optional[str] = None,
        source: Optional[InventorySource] = None,
        pattern: Optional[str] = None,
    ) -> List[Host]:
        """
        Filter hosts by criteria.

        Args:
            environment: Filter by environment (prod, staging, dev)
            group: Filter by Ansible group
            source: Filter by inventory source
            pattern: Filter by hostname pattern (regex)

        Returns:
            List of matching hosts
        """
        results = []
        pattern_re = re.compile(pattern, re.IGNORECASE) if pattern else None

        for host in self._hosts.values():
            # Environment filter
            if environment and host.environment != environment:
                continue

            # Group filter
            if group and group not in host.groups:
                continue

            # Source filter
            if source and host.source != source:
                continue

            # Pattern filter
            if pattern_re and not pattern_re.search(host.hostname):
                continue

            results.append(host)

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        env_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}

        for host in self._hosts.values():
            env = host.environment or "unknown"
            env_counts[env] = env_counts.get(env, 0) + 1

            source = host.source.value
            source_counts[source] = source_counts.get(source, 0) + 1

        return {
            "total_hosts": len(self._hosts),
            "total_aliases": len(self._aliases),
            "loaded_sources": [s.value for s in self._loaded_sources],
            "by_environment": env_counts,
            "by_source": source_counts,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
        }


# Singleton instance
_registry: Optional[HostRegistry] = None
_setup_callback: Optional[Callable] = None


def set_inventory_setup_callback(callback: Callable) -> None:
    """
    Set callback for inventory setup when no hosts found.

    The callback should be a function that handles the setup wizard
    and returns True if setup was successful.
    """
    global _setup_callback
    _setup_callback = callback


def get_host_registry(config: Optional[Dict[str, Any]] = None) -> HostRegistry:
    """Get the global HostRegistry instance."""
    global _registry

    if _registry is None:
        _registry = HostRegistry(config)
        _registry.load_all_sources()

        # If no hosts found and we have a setup callback, invoke it
        if _registry.is_empty() and _setup_callback:
            logger.info("No hosts found in inventory, triggering setup...")
            if _setup_callback():
                # Reload after setup
                _registry.load_all_sources(force_refresh=True)

    return _registry


def reset_host_registry() -> None:
    """Reset the global registry (for testing or reconfiguration)."""
    global _registry
    _registry = None
