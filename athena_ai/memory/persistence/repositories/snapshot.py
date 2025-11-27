"""
Snapshot Repository Mixin - Manages inventory snapshots.

Handles creation and retrieval of point-in-time inventory snapshots for backup/restore.
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.core.exceptions import PersistenceError

logger = logging.getLogger(__name__)


MAX_SNAPSHOT_LIMIT = 1000


class SnapshotRepositoryMixin:
    """Mixin for inventory snapshot operations."""

    def _init_snapshot_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize inventory snapshots table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                host_count INTEGER,
                snapshot_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

    def create_snapshot(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> int:
        """Create a snapshot of the current inventory.

        Args:
            name: Optional snapshot name (auto-generated if not provided).
            description: Optional description.

        Returns:
            Snapshot ID.
        """
        hosts = self.get_all_hosts()
        relations = self.get_relations()

        now = datetime.now()
        timestamp = now.isoformat()
        snapshot_data = {
            "hosts": hosts,
            "relations": relations,
            "created_at": timestamp,
        }

        snapshot_name = name or f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}"

        # Serialize snapshot data with fallback for non-JSON-serializable types
        try:
            serialized_data = json.dumps(snapshot_data, default=str)
        except (TypeError, ValueError) as e:
            raise PersistenceError(
                operation="create_snapshot",
                reason=f"Failed to serialize snapshot data: {e}",
                details={"snapshot_name": snapshot_name, "host_count": len(hosts)},
            ) from e

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO inventory_snapshots (name, description, host_count, snapshot_data, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                snapshot_name,
                description,
                len(hosts),
                serialized_data,
                timestamp,
            ))

            return cursor.lastrowid

    def list_snapshots(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List inventory snapshots.

        Args:
            limit: Maximum number of snapshots to return (1 to MAX_SNAPSHOT_LIMIT).

        Returns:
            List of snapshot dictionaries (without full data).

        Raises:
            ValueError: If limit is not a positive integer.
        """
        # Coerce to int if possible, reject non-numeric types
        if not isinstance(limit, int):
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                raise ValueError(f"limit must be an integer, got {type(limit).__name__}")

        # Reject non-positive values
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}")

        # Clamp to maximum allowed value
        limit = min(limit, MAX_SNAPSHOT_LIMIT)

        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, description, host_count, created_at
                FROM inventory_snapshots
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Get a snapshot by ID.

        Args:
            snapshot_id: Snapshot ID to retrieve.

        Returns:
            Snapshot dictionary with parsed data, or None if not found.
        """
        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
            row = cursor.fetchone()

            if row:
                result = self._row_to_dict(row)
                try:
                    result["snapshot_data"] = json.loads(result["snapshot_data"])
                except json.JSONDecodeError as e:
                    logger.error(
                        "Failed to deserialize snapshot data for snapshot_id=%s: %s",
                        snapshot_id,
                        e,
                    )
                    result["snapshot_data"] = None
                return result
            return None

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """Delete a snapshot.

        Args:
            snapshot_id: Snapshot ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
            return cursor.rowcount > 0
