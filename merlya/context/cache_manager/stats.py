"""
Cache Statistics.
"""

import threading
from typing import Any, Dict


class CacheStats:
    """Statistics for cache operations (thread-safe)."""

    def __init__(self):
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._cleanups = 0
        self._lock = threading.Lock()

    def get_hit_rate(self) -> float:
        """Calculate cache hit rate (thread-safe)."""
        with self._lock:
            total = self._hits + self._misses
            return self._hits / total if total > 0 else 0.0

    def record_hit(self):
        with self._lock:
            self._hits += 1

    def record_miss(self):
        with self._lock:
            self._misses += 1

    def record_eviction(self):
        with self._lock:
            self._evictions += 1

    def record_expiration(self):
        with self._lock:
            self._expirations += 1

    def record_cleanup(self):
        with self._lock:
            self._cleanups += 1

    def to_dict(self) -> Dict[str, Any]:
        """Get statistics as dictionary (thread-safe snapshot)."""
        with self._lock:
            hits = self._hits
            misses = self._misses
            total = hits + misses
            return {
                "hits": hits,
                "misses": misses,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "cleanups": self._cleanups,
                "hit_rate": round(hits / total, 3) if total > 0 else 0.0,
            }
