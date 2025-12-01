"""
Cache Manager Implementation.
"""

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from merlya.utils.logger import logger

from .executor import get_persistence_executor
from .models import CacheConfig, CacheEntry
from .stats import CacheStats


class CacheManager:
    """
    Intelligent cache manager with TTL and eviction strategies.

    Features:
    - Per-data-type TTL configuration
    - LRU-like eviction when max entries reached
    - Automatic background cleanup
    - Cache statistics
    - Thread-safe operations
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        """
        Initialize cache manager.

        Args:
            config: Cache configuration (uses defaults if not provided)
        """
        self.config = config or CacheConfig()
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self.stats = CacheStats()

        # Background cleanup
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()

        # Persistence
        self._repo = None

    @property
    def repo(self):
        """Lazy load repository for persistent caching."""
        if self._repo is None:
            try:
                from merlya.memory.persistence.inventory_repository import get_inventory_repository
                self._repo = get_inventory_repository()
            except Exception as e:
                logger.debug(f"Failed to load inventory repository: {e}", exc_info=True)
        return self._repo

    def start_cleanup_thread(self):
        """Start background cleanup thread (thread-safe)."""
        with self._lock:
            # Check if thread exists and is still alive
            if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
                return

            self._stop_cleanup.clear()
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                daemon=True,
                name="CacheCleanup"
            )
            self._cleanup_thread.start()
            logger.debug("Cache cleanup thread started")

    def stop_cleanup_thread(self):
        """Stop background cleanup thread (thread-safe)."""
        with self._lock:
            if self._cleanup_thread is None:
                return

            self._stop_cleanup.set()
            thread = self._cleanup_thread
            self._cleanup_thread = None

        # Join outside lock to avoid deadlock if cleanup loop needs lock
        thread.join(timeout=5)
        logger.debug("Cache cleanup thread stopped")

    def _cleanup_loop(self):
        """Background cleanup loop."""
        while not self._stop_cleanup.wait(self.config.cleanup_interval):
            try:
                self.cleanup_expired()
                self.stats.record_cleanup()
            except Exception as e:
                logger.debug(f"Cleanup error: {e}")

    def get(
        self,
        key: str,
        data_type: str = "default",
        default: Any = None,
    ) -> Any:
        """
        Get a value from cache.

        Args:
            key: Cache key
            data_type: Type of data (for TTL lookup)
            default: Default value if not found

        Returns:
            Cached value or default
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self.stats.record_miss()
                return default

            if entry.is_expired:
                del self._cache[key]
                self.stats.record_expiration()
                self.stats.record_miss()
                return default

            # Update access stats
            entry.access_count += 1
            entry.last_accessed = time.time()

            self.stats.record_hit()
            return entry.data

    def set(
        self,
        key: str,
        data: Any,
        data_type: str = "default",
        ttl: Optional[int] = None,
    ):
        """
        Set a value in cache.

        Args:
            key: Cache key
            data: Data to cache
            data_type: Type of data (for TTL lookup)
            ttl: Override TTL (uses config if not provided)
        """
        if ttl is None:
            ttl = self.config.ttl_config.get(
                data_type,
                self.config.ttl_config.get("default", 300)
            )

        with self._lock:
            # Check if we need to evict (only for new keys)
            if key not in self._cache and len(self._cache) >= self.config.max_entries:
                self._evict_lru()

            entry = CacheEntry(
                key=key,
                data=data,
                data_type=data_type,
                created_at=time.time(),
                ttl=ttl,
                access_count=0,
                last_accessed=time.time(),
            )
            self._cache[key] = entry

    def delete(self, key: str) -> bool:
        """
        Delete a key from cache.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self, data_type: Optional[str] = None):
        """
        Clear cache entries.

        Args:
            data_type: If provided, only clear entries of this type
        """
        with self._lock:
            if data_type is None:
                self._cache.clear()
            else:
                to_delete = [
                    key for key, entry in self._cache.items()
                    if entry.data_type == data_type
                ]
                for key in to_delete:
                    del self._cache[key]

    def cleanup_expired(self) -> int:
        """
        Remove expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]
            for key in expired:
                del self._cache[key]
                self.stats.record_expiration()

            return len(expired)

    def _evict_lru(self):
        """Evict least recently used entry."""
        if not self._cache:
            return

        # Find LRU entry
        lru_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].last_accessed
        )
        del self._cache[lru_key]
        self.stats.record_eviction()

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        data_type: str = "default",
        ttl: Optional[int] = None,
    ) -> Any:
        """
        Get value from cache or compute and cache it (thread-safe).

        Args:
            key: Cache key
            factory: Callable to generate value if not cached
            data_type: Type of data
            ttl: Override TTL

        Returns:
            Cached or computed value (can be None if factory returns None)
        """
        # Use sentinel to distinguish None from missing
        with self._lock:
            entry = self._cache.get(key)

            if entry is not None and not entry.is_expired:
                # Cache hit
                entry.access_count += 1
                entry.last_accessed = time.time()
                self.stats.record_hit()
                return entry.data

            # Cache miss - need to compute
            # Record miss stats
            if entry is not None:
                # Entry existed but expired
                del self._cache[key]
                self.stats.record_expiration()
            self.stats.record_miss()

        # Compute value outside lock to avoid blocking other threads
        value = factory()

        # Re-acquire lock to set value
        with self._lock:
            # Double-check: another thread may have set it while we computed
            entry = self._cache.get(key)
            if entry is not None and not entry.is_expired:
                # Another thread won - return their value
                return entry.data

            # We won - set our value
            if ttl is None:
                ttl = self.config.ttl_config.get(
                    data_type,
                    self.config.ttl_config.get("default", 300)
                )

            # Check if we need to evict
            if len(self._cache) >= self.config.max_entries:
                self._evict_lru()

            new_entry = CacheEntry(
                key=key,
                data=value,
                data_type=data_type,
                created_at=time.time(),
                ttl=ttl,
                access_count=0,
                last_accessed=time.time(),
            )
            self._cache[key] = new_entry

        return value

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            entries_by_type: Dict[str, int] = {}
            total_ttl: float = 0.0

            for entry in self._cache.values():
                entries_by_type[entry.data_type] = entries_by_type.get(entry.data_type, 0) + 1
                total_ttl += entry.time_to_live

            avg_ttl = total_ttl / len(self._cache) if self._cache else 0.0

            return {
                "entries": len(self._cache),
                "max_entries": self.config.max_entries,
                "entries_by_type": entries_by_type,
                "average_ttl_remaining": round(avg_ttl, 1),
                "stats": self.stats.to_dict(),
            }

    def get_entry_info(self, key: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific cache entry."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            return {
                "key": entry.key,
                "data_type": entry.data_type,
                "created_at": datetime.fromtimestamp(
                    entry.created_at, tz=timezone.utc
                ).isoformat(),
                "age_seconds": round(entry.age_seconds, 1),
                "ttl": entry.ttl,
                "time_to_live": round(entry.time_to_live, 1),
                "is_expired": entry.is_expired,
                "access_count": entry.access_count,
                "last_accessed": datetime.fromtimestamp(
                    entry.last_accessed, tz=timezone.utc
                ).isoformat() if entry.last_accessed else None,
            }

    # =========================================================================
    # Convenience methods for common data types
    # =========================================================================

    def cache_local_context(self, data: Dict[str, Any]):
        """Cache local machine context."""
        self.set("local_context", data, "local_context")

    def get_local_context(self) -> Optional[Dict[str, Any]]:
        """Get cached local context."""
        return self.get("local_context", "local_context")

    def cache_host_data(
        self,
        hostname: str,
        data: Dict[str, Any],
        data_type: str = "host_basic",
    ):
        """Cache data for a specific host."""
        key = f"host:{hostname}:{data_type}"
        self.set(key, data, data_type)

        # Persist asynchronously to avoid blocking cache operations
        if self.repo:
            # Deep copy mutable data to avoid race conditions if caller mutates
            data_copy = copy.deepcopy(data)
            ttl = self.config.ttl_config.get(data_type, 300)
            repo = self.repo  # Capture reference

            def persist():
                try:
                    repo.set_scan_cache(hostname, data_type, data_copy, ttl)
                except Exception as e:
                    logger.debug(f"Failed to persist cache for {hostname}: {e}")

            get_persistence_executor().submit(persist)

    # Sentinel value to distinguish "no data in DB" from "not yet checked"
    _NO_DATA_SENTINEL = object()

    def get_host_data(
        self,
        hostname: str,
        data_type: str = "host_basic",
    ) -> Optional[Dict[str, Any]]:
        """Get cached data for a specific host."""
        key = f"host:{hostname}:{data_type}"
        data = self.get(key, data_type)

        # Check if we have a cached "no data" sentinel
        if data is self._NO_DATA_SENTINEL:
            return None

        # Try persistent cache if not in memory
        if data is None and self.repo:
            try:
                cached = self.repo.get_scan_cache_by_hostname(hostname, data_type)
                if cached:
                    data_value = cached.get("data")
                    if data_value is not None:
                        self.set(key, data_value, data_type)
                        return data_value
                # Cache "no data" with short TTL to avoid repeated DB lookups
                self.set(key, self._NO_DATA_SENTINEL, data_type, ttl=60)
            except Exception as e:
                logger.debug(f"Failed to load from persistent cache for {hostname}: {e}")

        return data

    def invalidate_host(self, hostname: str):
        """Invalidate all cached data for a host (memory and persistent)."""
        with self._lock:
            to_delete = [
                key for key in self._cache.keys()
                if key.startswith(f"host:{hostname}:")
            ]
            for key in to_delete:
                del self._cache[key]

        # Also clear persistent cache
        if self.repo:
            try:
                self.repo.clear_host_cache(hostname)
            except Exception as e:
                logger.debug(f"Failed to clear persistent cache for {hostname}: {e}")

    def cache_inventory_search(
        self,
        query: str,
        results: List[Dict[str, Any]],
    ):
        """Cache inventory search results."""
        key = f"inventory_search:{query.lower()}"
        self.set(key, results, "inventory_search")

    def get_inventory_search(
        self,
        query: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached inventory search results."""
        key = f"inventory_search:{query.lower()}"
        return self.get(key, "inventory_search")
