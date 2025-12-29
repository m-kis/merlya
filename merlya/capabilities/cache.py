"""
Merlya Capabilities - Cache.

In-memory cache with TTL for capability detection results.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.capabilities.models import HostCapabilities, LocalCapabilities


class CapabilityCache:
    """In-memory cache for capability detection results."""

    def __init__(self, default_ttl: int = 86400):
        """
        Initialize capability cache.

        Args:
            default_ttl: Default TTL in seconds (24 hours).
        """
        self._host_cache: dict[str, HostCapabilities] = {}
        self._local_cache: LocalCapabilities | None = None
        self._lock = asyncio.Lock()
        self._default_ttl = default_ttl

    async def get_host(self, host_name: str) -> HostCapabilities | None:
        """
        Get cached host capabilities.

        Args:
            host_name: Name of the host.

        Returns:
            Cached capabilities if valid, None if expired or not found.
        """
        async with self._lock:
            caps = self._host_cache.get(host_name)
            if caps is None:
                return None
            if caps.is_expired():
                logger.debug(f"Cache expired for host {host_name}")
                del self._host_cache[host_name]
                return None
            return caps

    async def set_host(self, caps: HostCapabilities) -> None:
        """
        Cache host capabilities.

        Args:
            caps: Host capabilities to cache.
        """
        async with self._lock:
            caps.cached_at = datetime.now(UTC)
            if caps.ttl_seconds == 0:
                caps.ttl_seconds = self._default_ttl
            self._host_cache[caps.host_name] = caps
            logger.debug(f"🗄️ Cached capabilities for host {caps.host_name}")

    async def get_local(self) -> LocalCapabilities | None:
        """
        Get cached local capabilities.

        Returns:
            Cached local capabilities if valid, None otherwise.
        """
        async with self._lock:
            if self._local_cache is None:
                return None
            if self._local_cache.is_expired():
                logger.debug("Local cache expired")
                self._local_cache = None
                return None
            return self._local_cache

    async def set_local(self, caps: LocalCapabilities) -> None:
        """
        Cache local capabilities.

        Args:
            caps: Local capabilities to cache.
        """
        async with self._lock:
            caps.cached_at = datetime.now(UTC)
            self._local_cache = caps
            logger.debug("🗄️ Cached local capabilities")

    async def invalidate_host(self, host_name: str) -> None:
        """
        Remove host from cache.

        Args:
            host_name: Name of the host to invalidate.
        """
        async with self._lock:
            if host_name in self._host_cache:
                del self._host_cache[host_name]
                logger.debug(f"Invalidated cache for host {host_name}")

    async def invalidate_all(self) -> None:
        """Clear all cached capabilities."""
        async with self._lock:
            self._host_cache.clear()
            self._local_cache = None
            logger.debug("Invalidated all capability caches")

    async def cleanup_expired(self) -> int:
        """
        Remove all expired entries from cache.

        Returns:
            Number of entries removed.
        """
        async with self._lock:
            expired = [name for name, caps in self._host_cache.items() if caps.is_expired()]
            for name in expired:
                del self._host_cache[name]

            if self._local_cache and self._local_cache.is_expired():
                self._local_cache = None
                expired.append("__local__")

            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired cache entries")
            return len(expired)

    @property
    def size(self) -> int:
        """Get number of cached hosts."""
        return len(self._host_cache)
