"""
Repository Mixins for InventoryRepository.

This package provides modular mixins that implement specific repository concerns:
- SourceRepositoryMixin: Inventory source management
- HostRepositoryMixin: Host CRUD with versioning
- RelationRepositoryMixin: Host relationships
- ScanCacheRepositoryMixin: Scan result caching with TTL
- LocalContextRepositoryMixin: Local machine context
- SnapshotRepositoryMixin: Point-in-time snapshots
"""

from athena_ai.memory.persistence.repositories.host import HostData, HostRepositoryMixin
from athena_ai.memory.persistence.repositories.local_context import (
    LocalContextRepositoryMixin,
)
from athena_ai.memory.persistence.repositories.relation import RelationRepositoryMixin
from athena_ai.memory.persistence.repositories.scan_cache import (
    ScanCacheRepositoryMixin,
)
from athena_ai.memory.persistence.repositories.snapshot import SnapshotRepositoryMixin
from athena_ai.memory.persistence.repositories.source import SourceRepositoryMixin

__all__ = [
    "HostData",
    "SourceRepositoryMixin",
    "HostRepositoryMixin",
    "RelationRepositoryMixin",
    "ScanCacheRepositoryMixin",
    "LocalContextRepositoryMixin",
    "SnapshotRepositoryMixin",
]
