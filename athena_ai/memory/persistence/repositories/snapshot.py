"""
Snapshot Repository Mixin - Manages inventory snapshots.

Handles creation and retrieval of point-in-time inventory snapshots for backup/restore.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


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

        snapshot_data = {
            "hosts": hosts,
            "relations": relations,
            "created_at": datetime.now().isoformat(),
        }

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO inventory_snapshots (name, description, host_count, snapshot_data, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name or f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            description,
            len(hosts),
            json.dumps(snapshot_data),
            datetime.now().isoformat(),
        ))

        snapshot_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return snapshot_id

    def list_snapshots(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List inventory snapshots.

        Args:
            limit: Maximum number of snapshots to return.

        Returns:
            List of snapshot dictionaries (without full data).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, name, description, host_count, created_at
            FROM inventory_snapshots
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Get a snapshot by ID.

        Args:
            snapshot_id: Snapshot ID to retrieve.

        Returns:
            Snapshot dictionary with parsed data, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            result = self._row_to_dict(row)
            result["snapshot_data"] = json.loads(result["snapshot_data"])
            return result
        return None

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """Delete a snapshot.

        Args:
            snapshot_id: Snapshot ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()
        return deleted
