"""
Repository Mixins for InventoryRepository.

This package provides modular mixins that implement specific repository concerns:

Mixins:
    - SourceRepositoryMixin: Inventory source management
    - HostRepositoryMixin: Host CRUD with versioning
    - RelationRepositoryMixin: Host relationships
    - ScanCacheRepositoryMixin: Scan result caching with TTL
    - LocalContextRepositoryMixin: Local machine context
    - SnapshotRepositoryMixin: Point-in-time snapshots

Data Types:
    - HostData: Dataclass for host information used in bulk imports
"""

from merlya.memory.persistence.repositories.host import HostData, HostRepositoryMixin
from merlya.memory.persistence.repositories.local_context import (
    LocalContextRepositoryMixin,
)
from merlya.memory.persistence.repositories.relation import (
    BatchRelationResult,
    RelationRepositoryMixin,
)
from merlya.memory.persistence.repositories.scan_cache import (
    ScanCacheRepositoryMixin,
)
from merlya.memory.persistence.repositories.snapshot import SnapshotRepositoryMixin
from merlya.memory.persistence.repositories.source import SourceRepositoryMixin

__all__ = [
    "BatchRelationResult",
    "HostData",
    "SourceRepositoryMixin",
    "HostRepositoryMixin",
    "RelationRepositoryMixin",
    "ScanCacheRepositoryMixin",
    "LocalContextRepositoryMixin",
    "SnapshotRepositoryMixin",
]
