"""
Cache Manager Package.
"""

import threading
from typing import Optional

from .manager import CacheManager
from .models import CacheConfig

# Thread-safe singleton
_cache_manager: Optional[CacheManager] = None
_cache_manager_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """Get the cache manager singleton (thread-safe).

    Uses double-check locking with local variable to ensure
    thread-safe lazy initialization.
    """
    global _cache_manager
    # First check without lock (fast path)
    manager = _cache_manager
    if manager is not None:
        return manager

    with _cache_manager_lock:
        # Double-check inside lock
        if _cache_manager is None:
            _cache_manager = CacheManager()
        return _cache_manager


__all__ = ["CacheManager", "CacheConfig", "get_cache_manager"]
