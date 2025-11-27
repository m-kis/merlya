"""
Intelligent Cache Manager for host scan data.

Features:
- TTL-based caching with per-data-type configuration
- Cache invalidation strategies
- Cache statistics and monitoring
- Memory-efficient storage
- Automatic cleanup of stale entries
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from athena_ai.utils.logger import logger


@dataclass
class CacheConfig:
    """Configuration for cache behavior."""

    # Default TTLs (seconds) by data type
    ttl_config: Dict[str, int] = field(default_factory=lambda: {
        # Local machine data
        "local_context": 43200,     # 12 hours
        "local_services": 3600,     # 1 hour
        "local_processes": 300,     # 5 minutes

        # Remote host data
        "host_basic": 300,          # 5 minutes - connectivity, DNS
        "host_system": 1800,        # 30 minutes - OS, hardware
        "host_services": 900,       # 15 minutes - running services
        "host_packages": 3600,      # 1 hour - installed packages
        "host_metrics": 60,         # 1 minute - CPU, memory usage

        # Inventory data
        "inventory_list": 300,      # 5 minutes
        "inventory_search": 120,    # 2 minutes
        "relations": 3600,          # 1 hour

        # Default for unknown types
        "default": 300,             # 5 minutes
    })

    # Cleanup settings
    cleanup_interval: int = 300     # Run cleanup every 5 minutes
    max_entries: int = 1000         # Maximum cached entries
    max_memory_mb: int = 100        # Maximum memory usage

    # Stale entry threshold (multiplier of TTL)
    stale_threshold: float = 2.0


@dataclass
class CacheEntry:
    """A single cache entry."""

    key: str
    data: Any
    data_type: str
    created_at: float  # timestamp
    ttl: int
    access_count: int = 0
    last_accessed: float = 0

    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return self.age_seconds > self.ttl

    @property
    def time_to_live(self) -> float:
        """Get remaining TTL in seconds."""
        return max(0, self.ttl - self.age_seconds)


class CacheStats:
    """Statistics for cache operations."""

    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0
        self.cleanups = 0
        self._lock = threading.Lock()

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def record_hit(self):
        with self._lock:
            self.hits += 1

    def record_miss(self):
        with self._lock:
            self.misses += 1

    def record_eviction(self):
        with self._lock:
            self.evictions += 1

    def record_expiration(self):
        with self._lock:
            self.expirations += 1

    def record_cleanup(self):
        with self._lock:
            self.cleanups += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "cleanups": self.cleanups,
            "hit_rate": round(self.hit_rate, 3),
        }


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
                from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
                self._repo = get_inventory_repository()
            except Exception:
                pass
        return self._repo

    def start_cleanup_thread(self):
        """Start background cleanup thread."""
        if self._cleanup_thread is not None:
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
        """Stop background cleanup thread."""
        if self._cleanup_thread is None:
            return

        self._stop_cleanup.set()
        self._cleanup_thread.join(timeout=5)
        self._cleanup_thread = None
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
            # Check if we need to evict
            if len(self._cache) >= self.config.max_entries:
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
        Get value from cache or compute and cache it.

        Args:
            key: Cache key
            factory: Callable to generate value if not cached
            data_type: Type of data
            ttl: Override TTL

        Returns:
            Cached or computed value
        """
        value = self.get(key, data_type)
        if value is not None:
            return value

        value = factory()
        if value is not None:
            self.set(key, value, data_type, ttl)

        return value

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            entries_by_type: Dict[str, int] = {}
            total_ttl = 0

            for entry in self._cache.values():
                entries_by_type[entry.data_type] = entries_by_type.get(entry.data_type, 0) + 1
                total_ttl += entry.time_to_live

            avg_ttl = total_ttl / len(self._cache) if self._cache else 0

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

        # Also persist to database if available
        if self.repo:
            try:
                ttl = self.config.ttl_config.get(data_type, 300)
                self.repo.set_scan_cache(hostname, data_type, data, ttl)
            except Exception as e:
                logger.debug(f"Failed to persist cache for {hostname}: {e}")

    def get_host_data(
        self,
        hostname: str,
        data_type: str = "host_basic",
    ) -> Optional[Dict[str, Any]]:
        """Get cached data for a specific host."""
        key = f"host:{hostname}:{data_type}"
        data = self.get(key, data_type)

        # Try persistent cache if not in memory
        if data is None and self.repo:
            try:
                cached = self.repo.get_scan_cache(hostname, data_type)
                if cached:
                    # Re-populate memory cache
                    self.set(key, cached.get("data"), data_type)
                    return cached.get("data")
            except Exception:
                pass

        return data

    def invalidate_host(self, hostname: str):
        """Invalidate all cached data for a host."""
        with self._lock:
            to_delete = [
                key for key in self._cache.keys()
                if key.startswith(f"host:{hostname}:")
            ]
            for key in to_delete:
                del self._cache[key]

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


# Singleton
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Get the cache manager singleton."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
