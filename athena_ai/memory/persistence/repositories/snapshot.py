"""
Snapshot Repository Mixin - Manages inventory snapshots.

Handles creation and retrieval of point-in-time inventory snapshots for backup/restore.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


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

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO inventory_snapshots (name, description, host_count, snapshot_data, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                name or f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}",
                description,
                len(hosts),
                json.dumps(snapshot_data),
                timestamp,
            ))

            snapshot_id = cursor.lastrowid
            conn.commit()
            return snapshot_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, description, host_count, created_at
                FROM inventory_snapshots
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Get a snapshot by ID.

        Args:
            snapshot_id: Snapshot ID to retrieve.

        Returns:
            Snapshot dictionary with parsed data, or None if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
            row = cursor.fetchone()

            if row:
                result = self._row_to_dict(row)
                result["snapshot_data"] = json.loads(result["snapshot_data"])
                return result
            return None
        finally:
            conn.close()

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """Delete a snapshot.

        Args:
            snapshot_id: Snapshot ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
            deleted = cursor.rowcount > 0

            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
