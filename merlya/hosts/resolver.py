"""
Merlya Hosts - Host resolver.

Resolves hostnames with priority: Inventory -> Local -> DNS.
"""

from __future__ import annotations

import asyncio
import re
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.persistence import HostRepository

# RFC 1035 max hostname length
MAX_HOSTNAME_LENGTH = 253

# Valid hostname pattern (RFC 1123)
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(\.[a-zA-Z0-9-]{1,63})*$"
)

# Valid IP address pattern (IPv4)
IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)


class InvalidHostQueryError(Exception):
    """Raised when host query is invalid."""

    pass


class HostNotFoundError(Exception):
    """Raised when a host cannot be resolved."""

    def __init__(self, message: str, suggestions: list[str] | None = None) -> None:
        """
        Initialize error.

        Args:
            message: Error message.
            suggestions: Similar host names for suggestion.
        """
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions or []


@dataclass
class ResolvedHost:
    """Result of host resolution."""

    query: str  # Original query
    hostname: str  # Resolved hostname
    ip: str  # Resolved IP
    source: str  # "inventory", "local", or "dns"
    host_id: str | None = None  # ID in inventory if found


class HostResolver:
    """
    Host resolver with priority-based lookup.

    Resolution order:
    1. Merlya inventory (SQLite)
    2. Local resolution (/etc/hosts, mDNS)
    3. DNS standard
    """

    def __init__(
        self,
        host_repo: HostRepository,
        local_timeout: float = 2.0,
        dns_timeout: float = 5.0,
    ) -> None:
        """
        Initialize resolver.

        Args:
            host_repo: Host repository for inventory lookup.
            local_timeout: Timeout for local resolution.
            dns_timeout: Timeout for DNS resolution.
        """
        self.host_repo = host_repo
        self.local_timeout = local_timeout
        self.dns_timeout = dns_timeout

    def _validate_query(self, query: str) -> str:
        """
        Validate and sanitize host query.

        Args:
            query: Raw query string.

        Returns:
            Sanitized query string.

        Raises:
            InvalidHostQueryError: If query is invalid.
        """
        # Check for empty/whitespace
        if not query or not query.strip():
            raise InvalidHostQueryError("Host query cannot be empty")

        query = query.strip()

        # Check for null bytes (security)
        if "\x00" in query:
            raise InvalidHostQueryError("Host query contains null bytes")

        # Check length
        if len(query) > MAX_HOSTNAME_LENGTH:
            raise InvalidHostQueryError(
                f"Host query exceeds maximum length ({MAX_HOSTNAME_LENGTH} chars)"
            )

        # Allow IP addresses
        if IPV4_PATTERN.match(query):
            return query

        # Allow inventory names (alphanumeric, dash, underscore, dot)
        if all(c.isalnum() or c in "-_." for c in query):
            return query

        # Validate hostname format
        if not HOSTNAME_PATTERN.match(query):
            raise InvalidHostQueryError(f"Invalid host query format: '{query}'")

        return query

    async def resolve(self, query: str) -> ResolvedHost:
        """
        Resolve a host.

        Args:
            query: Hostname, IP, or host name from inventory.

        Returns:
            ResolvedHost with IP and source.

        Raises:
            InvalidHostQueryError: If query is invalid.
            HostNotFoundError: If host cannot be resolved.
        """
        # Validate input
        query = self._validate_query(query)

        # 1. Check inventory
        host = await self.host_repo.get_by_name(query)
        if host:
            # If we have an IP in metadata, use it
            ip = host.metadata.get("ip") or await self._resolve_dns(host.hostname)
            return ResolvedHost(
                query=query,
                hostname=host.hostname,
                ip=ip,
                source="inventory",
                host_id=host.id,
            )

        # 2. Try local resolution (short timeout)
        try:
            ip = await asyncio.wait_for(
                asyncio.to_thread(socket.gethostbyname, query),
                timeout=self.local_timeout,
            )
            logger.debug(f"🌐 Resolved '{query}' via local: {ip}")
            return ResolvedHost(
                query=query,
                hostname=query,
                ip=ip,
                source="local",
            )
        except (TimeoutError, socket.gaierror):
            pass

        # 3. Try DNS (longer timeout)
        try:
            ip = await asyncio.wait_for(
                self._resolve_dns(query),
                timeout=self.dns_timeout,
            )
            logger.debug(f"🌐 Resolved '{query}' via DNS: {ip}")
            return ResolvedHost(
                query=query,
                hostname=query,
                ip=ip,
                source="dns",
            )
        except (TimeoutError, socket.gaierror):
            pass

        # 4. Not found
        suggestions = await self._find_similar_hosts(query)
        raise HostNotFoundError(
            f"Host '{query}' could not be resolved",
            suggestions=suggestions,
        )

    async def _resolve_dns(self, hostname: str) -> str:
        """Async DNS resolution."""
        loop = asyncio.get_event_loop()
        result = await loop.getaddrinfo(
            hostname,
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        return result[0][4][0]

    async def _find_similar_hosts(self, query: str) -> list[str]:
        """Find similar host names for suggestions."""
        all_hosts = await self.host_repo.get_all()
        similar: list[str] = []

        query_lower = query.lower()
        for host in all_hosts:
            name_lower = host.name.lower()
            # Simple substring matching
            if query_lower in name_lower or name_lower in query_lower:
                similar.append(host.name)

        return similar[:5]
