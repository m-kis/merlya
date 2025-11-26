"""
Smart caching system for infrastructure context.
Auto-detects changes and refreshes only what's needed.
Persists cache to disk to avoid unnecessary rescans.
"""
import time
import hashlib
import json
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from athena_ai.utils.logger import logger


class SmartCache:
    """
    Intelligent cache that auto-detects when data is stale.
    Each cache entry has:
    - TTL (time to live)
    - Fingerprint (to detect changes)
    - Lazy refresh (only when accessed)
    - Disk persistence (survives restarts)
    """

    def __init__(self):
        self.cache_dir = Path.home() / ".athena" / "cache"
        self.cache_file = self.cache_dir / "context_cache.json"
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.config = {
            # Fast-changing data (short TTL)
            "processes": {"ttl": 30, "fingerprint_fn": None},  # 30 seconds
            "services": {"ttl": 60, "fingerprint_fn": None},  # 1 minute

            # Medium-changing data
            "local": {"ttl": 300, "fingerprint_fn": None},  # 5 minutes

            # Slow-changing data (long TTL + fingerprint)
            "inventory": {
                "ttl": 3600,  # 1 hour
                "fingerprint_fn": lambda: self._file_fingerprint("/etc/hosts")
            },

            # Remote hosts - refresh only on demand or when inventory changes
            "remote_hosts": {"ttl": 86400, "fingerprint_fn": None},  # 24 hours (host info rarely changes)
        }

        # Load existing cache from disk
        self._load_cache()

    def _load_cache(self):
        """Load cache from disk if exists and validate timestamps."""
        if not self.cache_file.exists():
            logger.debug("No cache file found - starting fresh")
            return

        try:
            with open(self.cache_file, 'r') as f:
                saved_cache = json.load(f)

            now = time.time()
            valid_entries = 0

            for key, entry in saved_cache.items():
                # Validate entry has required fields
                if "timestamp" not in entry or "data" not in entry:
                    continue

                # Check if still within TTL
                age = now - entry["timestamp"]
                config = self.config.get(key, {"ttl": 300})
                ttl = config["ttl"]

                if age < ttl:
                    self.cache[key] = entry
                    valid_entries += 1
                    logger.debug(f"Loaded cached {key} (age: {int(age)}s, TTL: {ttl}s)")
                else:
                    logger.debug(f"Skipped expired {key} (age: {int(age)}s, TTL: {ttl}s)")

            if valid_entries > 0:
                logger.info(f"Loaded {valid_entries} valid cache entries from disk")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")

    def _save_cache(self):
        """Save current cache to disk."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
            logger.debug(f"Cache saved to {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def _file_fingerprint(self, filepath: str) -> Optional[str]:
        """Generate MD5 fingerprint of a file."""
        try:
            path = Path(filepath)
            if not path.exists():
                return None

            content = path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except Exception:
            return None

    def get(self, key: str, refresh_fn: Callable[[], Any]) -> Any:
        """
        Get cached value or refresh if stale.

        Args:
            key: Cache key (e.g., 'inventory', 'processes')
            refresh_fn: Function to call to refresh the data

        Returns:
            Cached or fresh data
        """
        now = time.time()

        # Check if we have cached data
        if key in self.cache:
            entry = self.cache[key]
            age = now - entry["timestamp"]
            config = self.config.get(key, {"ttl": 300})

            # Check TTL
            if age < config["ttl"]:
                # Check fingerprint if configured
                fingerprint_fn = config.get("fingerprint_fn")
                if fingerprint_fn:
                    current_fingerprint = fingerprint_fn()
                    if current_fingerprint == entry.get("fingerprint"):
                        logger.debug(f"Cache HIT for {key} (age: {int(age)}s)")
                        return entry["data"]
                    else:
                        logger.info(f"Cache INVALIDATED for {key} (fingerprint changed)")
                else:
                    logger.debug(f"Cache HIT for {key} (age: {int(age)}s)")
                    return entry["data"]
            else:
                logger.debug(f"Cache EXPIRED for {key} (age: {int(age)}s, TTL: {config['ttl']}s)")

        # Cache miss or expired - refresh
        logger.info(f"Refreshing {key}...")
        data = refresh_fn()

        # Store in cache
        config = self.config.get(key, {"ttl": 300})
        entry = {
            "data": data,
            "timestamp": now,
        }

        # Add fingerprint if configured
        fingerprint_fn = config.get("fingerprint_fn")
        if fingerprint_fn:
            entry["fingerprint"] = fingerprint_fn()

        self.cache[key] = entry

        # Save cache to disk
        self._save_cache()

        return data

    def invalidate(self, key: str):
        """Force invalidate a cache entry."""
        if key in self.cache:
            logger.info(f"Cache INVALIDATED manually: {key}")
            del self.cache[key]
            self._save_cache()

    def invalidate_all(self):
        """Clear all cache."""
        logger.info("Cache CLEARED (all entries)")
        self.cache.clear()
        self._save_cache()

    def set_ttl(self, key: str, ttl: int):
        """Dynamically adjust TTL for a cache key."""
        if key not in self.config:
            self.config[key] = {"ttl": ttl}
        else:
            self.config[key]["ttl"] = ttl
        logger.debug(f"TTL for {key} set to {ttl}s")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about cache state."""
        now = time.time()
        stats = {}

        for key, entry in self.cache.items():
            age = now - entry["timestamp"]
            config = self.config.get(key, {"ttl": 300})
            ttl = config["ttl"]

            stats[key] = {
                "age_seconds": int(age),
                "ttl_seconds": ttl,
                "valid": age < ttl,
                "has_fingerprint": "fingerprint" in entry,
            }

        return stats
