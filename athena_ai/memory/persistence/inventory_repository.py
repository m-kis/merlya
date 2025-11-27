"""
Inventory Repository - Unified persistence for inventory v2.

This module provides the main InventoryRepository class that combines all
repository mixins for a complete inventory management solution.

Manages:
- Hosts with versioning
- Inventory sources
- Host relations
- Scan cache
- Local context
- Snapshots
"""

from typing import Any, Dict, Optional

from athena_ai.memory.persistence.base import BaseRepository
from athena_ai.memory.persistence.repositories import (
    HostRepositoryMixin,
    LocalContextRepositoryMixin,
    RelationRepositoryMixin,
    ScanCacheRepositoryMixin,
    SnapshotRepositoryMixin,
    SourceRepositoryMixin,
)
from athena_ai.utils.logger import logger


class InventoryRepository(
    SourceRepositoryMixin,
    HostRepositoryMixin,
    RelationRepositoryMixin,
    ScanCacheRepositoryMixin,
    LocalContextRepositoryMixin,
    SnapshotRepositoryMixin,
    BaseRepository,
):
    """
    Repository for the inventory system.

    Provides CRUD operations for:
    - Hosts (with versioning)
    - Inventory sources
    - Host relations
    - Scan cache
    - Local machine context
    - Inventory snapshots

    This class combines functionality from multiple mixins:
    - SourceRepositoryMixin: add_source, get_source, list_sources, delete_source
    - HostRepositoryMixin: add_host, get_host_by_name, search_hosts, etc.
    - RelationRepositoryMixin: add_relation, get_relations, validate_relation
    - ScanCacheRepositoryMixin: save_scan_cache, get_scan_cache, cleanup
    - LocalContextRepositoryMixin: save_local_context, get_local_context
    - SnapshotRepositoryMixin: create_snapshot, list_snapshots, get_snapshot

    Usage:
        from athena_ai.memory.persistence.inventory_repository import (
            get_inventory_repository
        )

        repo = get_inventory_repository()
        repo.add_host("web-server-01", ip_address="10.0.0.1")
    """

    def get_stats(self) -> Dict[str, Any]:
        """Get inventory statistics.

        Returns:
            Dictionary with counts and breakdowns:
            - total_hosts: Total number of hosts
            - by_environment: Host count per environment
            - by_source: Host count per source
            - total_relations: Total relations
            - validated_relations: User-validated relations
            - cached_scans: Active (non-expired) cache entries
            - error: Error message if stats retrieval failed (partial results)
        """
        from datetime import datetime, timezone

        stats: Dict[str, Any] = {}

        try:
            # Use context manager to ensure connection is always closed
            with self._connection() as conn:
                cursor = conn.cursor()

                # Total hosts
                cursor.execute("SELECT COUNT(*) FROM hosts_v2")
                stats["total_hosts"] = cursor.fetchone()[0]

                # By environment
                cursor.execute("""
                    SELECT environment, COUNT(*) FROM hosts_v2
                    GROUP BY environment
                """)
                stats["by_environment"] = {row[0] or "unknown": row[1] for row in cursor.fetchall()}

                # By source (group by name to match dict key)
                cursor.execute("""
                    SELECT s.name, COUNT(h.id)
                    FROM inventory_sources s
                    LEFT JOIN hosts_v2 h ON h.source_id = s.id
                    GROUP BY s.name
                """)
                stats["by_source"] = {row[0]: row[1] for row in cursor.fetchall()}

                # Relations
                cursor.execute("SELECT COUNT(*) FROM host_relations")
                stats["total_relations"] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM host_relations WHERE validated_by_user = 1")
                stats["validated_relations"] = cursor.fetchone()[0]

                # Cache - use UTC for consistent timezone handling
                cursor.execute(
                    "SELECT COUNT(*) FROM scan_cache WHERE expires_at > ?",
                    (datetime.now(timezone.utc).isoformat(),)
                )
                stats["cached_scans"] = cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to retrieve inventory stats: {e}")
            stats["error"] = str(e)

        return stats


def get_inventory_repository(db_path: Optional[str] = None) -> InventoryRepository:
    """Get the inventory repository singleton.

    The InventoryRepository class implements thread-safe singleton semantics
    via __new__. Calling this function (or InventoryRepository() directly)
    returns the same instance after the first call.

    Args:
        db_path: Optional database path. Only used on first instantiation.
            Subsequent calls ignore this parameter (a warning is logged if
            a different path is provided).

    Returns:
        The shared InventoryRepository singleton instance.

    Note:
        For testing, use InventoryRepository.reset_instance() to clear
        the singleton before creating a new instance with a different path.
    """
    return InventoryRepository(db_path)
