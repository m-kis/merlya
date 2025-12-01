"""
Cache Manager Models.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict


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
