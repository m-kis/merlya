"""
Inventory Source Manager - Gestion intelligente des sources d'inventaire.

Fonctionnalités:
- Multiple sources d'inventaire (local, fichiers, API)
- Résolution case-insensitive des hostnames
- Cache intelligent avec refresh
- Merge de sources multiples
"""
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path
import json
from athena_ai.utils.logger import logger


class InventorySourceManager:
    """
    Gère multiple sources d'inventaire avec intelligence.

    Features:
    - Case-insensitive hostname resolution
    - Multiple sources (primary + customs)
    - Smart caching
    - Merge strategy
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize inventory source manager.

        Args:
            config: Configuration dict with sources
        """
        self.config = config or {}
        self.primary_source = self.config.get('primary_source', '/etc/hosts')
        self.custom_sources = self.config.get('custom_sources', [])
        self._cache: Optional[Dict[str, str]] = None

    def get_inventory(self, refresh: bool = False) -> Dict[str, str]:
        """
        Get merged inventory from all sources.

        Args:
            refresh: Force refresh from sources

        Returns:
            Dict mapping hostname -> IP
        """
        if self._cache and not refresh:
            return self._cache

        inventory = {}

        # Load from primary source (e.g., /etc/hosts via ContextManager)
        # This will be integrated with existing ContextManager
        # For now, return empty dict (will be populated by ContextManager)

        self._cache = inventory
        return inventory

    def resolve_hostname(
        self,
        hostname: str,
        inventory: Dict[str, str],
        case_sensitive: bool = False
    ) -> Optional[Tuple[str, str]]:
        """
        Resolve hostname to canonical form and IP.

        Handles case-insensitive matching by default.

        Args:
            hostname: Hostname to resolve (e.g., "unifyqarcdb")
            inventory: Current inventory dict
            case_sensitive: If True, exact match only

        Returns:
            (canonical_hostname, ip_address) or None

        Examples:
            >>> resolve_hostname("db-qarc", inventory)
            ("db-qarc-1", "192.0.2.10")

            >>> resolve_hostname("lb-prod", inventory)
            ("lb-prod-1", "192.168.1.10")  # Partial match
        """
        if not hostname:
            return None

        # Exact match (case-sensitive if requested)
        if case_sensitive:
            ip = inventory.get(hostname)
            if ip:
                return (hostname, ip)
            return None

        # Case-insensitive exact match
        hostname_lower = hostname.lower()
        for host, ip in inventory.items():
            if host.lower() == hostname_lower:
                logger.debug(f"Hostname resolved: {hostname} → {host} ({ip})")
                return (host, ip)

        # Partial match (contains)
        # Useful for queries like "lb-prod" matching "lb-prod-1"
        matches = []
        for host, ip in inventory.items():
            if hostname_lower in host.lower():
                matches.append((host, ip))

        if len(matches) == 1:
            # Single partial match - use it
            host, ip = matches[0]
            logger.debug(f"Hostname resolved (partial): {hostname} → {host} ({ip})")
            return matches[0]
        elif len(matches) > 1:
            # Multiple matches - log warning, return first
            logger.warning(
                f"Multiple partial matches for '{hostname}': "
                f"{[h for h, _ in matches]}. Using first: {matches[0][0]}"
            )
            return matches[0]

        # No match
        logger.warning(f"Hostname not found: {hostname}")
        return None

    def find_similar_hostnames(
        self,
        hostname: str,
        inventory: Dict[str, str],
        max_results: int = 5
    ) -> List[Tuple[str, str, float]]:
        """
        Find similar hostnames using fuzzy matching.

        Args:
            hostname: Hostname to search for
            inventory: Current inventory
            max_results: Maximum number of results

        Returns:
            List of (hostname, ip, similarity_score)
        """
        from difflib import SequenceMatcher

        hostname_lower = hostname.lower()
        matches = []

        for host, ip in inventory.items():
            similarity = SequenceMatcher(
                None,
                hostname_lower,
                host.lower()
            ).ratio()

            if similarity > 0.6:  # Threshold for similarity
                matches.append((host, ip, similarity))

        # Sort by similarity descending
        matches.sort(key=lambda x: x[2], reverse=True)

        return matches[:max_results]


class DataAvailability:
    """
    Checks what data is available vs what's needed for a query.
    """

    def __init__(self):
        self.required_data_types = {
            'analyze': ['processes', 'metrics', 'services', 'os'],
            'list': ['inventory'],
            'monitor': ['metrics'],
            'status': ['services'],
        }

    def check(
        self,
        query_type: str,
        available_data: Dict[str, Any],
        target_host: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Check data availability for a query type.

        Args:
            query_type: Type of query (analyze, list, monitor, status)
            available_data: Currently available data
            target_host: Specific host to check (if applicable)

        Returns:
            {
                'has_required': bool,
                'available': List[str],
                'missing': List[str],
                'collection_needed': bool,
                'collection_method': 'ssh' | 'api' | None
            }
        """
        required = self.required_data_types.get(query_type, [])

        available = []
        missing = []

        for data_type in required:
            if self._is_available(data_type, available_data, target_host):
                available.append(data_type)
            else:
                missing.append(data_type)

        collection_needed = len(missing) > 0
        collection_method = 'ssh' if collection_needed else None

        return {
            'has_required': len(missing) == 0,
            'available': available,
            'missing': missing,
            'collection_needed': collection_needed,
            'collection_method': collection_method
        }

    def _is_available(
        self,
        data_type: str,
        available_data: Dict[str, Any],
        target_host: Optional[str]
    ) -> bool:
        """Check if specific data type is available."""
        if data_type == 'inventory':
            return bool(available_data.get('inventory'))

        if data_type == 'processes':
            if not target_host:
                return False
            remote_hosts = available_data.get('remote_hosts', {})
            host_data = remote_hosts.get(target_host, {})
            return 'processes' in host_data

        if data_type == 'metrics':
            if not target_host:
                return False
            remote_hosts = available_data.get('remote_hosts', {})
            host_data = remote_hosts.get(target_host, {})
            return 'metrics' in host_data or 'cpu' in host_data

        if data_type == 'services':
            if not target_host:
                return False
            remote_hosts = available_data.get('remote_hosts', {})
            host_data = remote_hosts.get(target_host, {})
            return 'services' in host_data

        if data_type == 'os':
            if not target_host:
                return False
            remote_hosts = available_data.get('remote_hosts', {})
            host_data = remote_hosts.get(target_host, {})
            return 'os' in host_data

        return False
