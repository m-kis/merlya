"""
Source Repository Mixin - Manages inventory sources.

Handles CRUD operations for inventory sources (manual, file imports, API, etc.).
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


class SourceRepositoryMixin:
    """Mixin for inventory source operations."""

    def _init_source_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize inventory sources table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                file_path TEXT,
                import_method TEXT DEFAULT 'manual',
                host_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT
            )
        """)

    def add_source(
        self,
        name: str,
        source_type: str,
        file_path: Optional[str] = None,
        import_method: str = "manual",
        metadata: Optional[Dict] = None,
    ) -> int:
        """Add a new inventory source or return existing one.

        If a source with the same name already exists, returns its ID
        instead of raising an error.

        Args:
            name: Unique source name.
            source_type: Type of source (manual, file, api, etc.).
            file_path: Optional path to source file.
            import_method: How the source was imported.
            metadata: Optional metadata dictionary.

        Returns:
            The source ID (existing or newly created).

        Raises:
            ValueError: If source was deleted during creation (race condition).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO inventory_sources
                (name, source_type, file_path, import_method, host_count, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """, (name, source_type, file_path, import_method, now, now, json.dumps(metadata or {})))

            source_id = cursor.lastrowid
            conn.commit()
        except sqlite3.IntegrityError:
            # Source with this name already exists, return existing ID
            cursor.execute("SELECT id FROM inventory_sources WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                source_id = row[0]
            else:
                # Concurrent delete occurred - reraise to let caller handle
                conn.close()
                raise ValueError(f"Source '{name}' was deleted during creation")
        finally:
            conn.close()

        return source_id

    def get_source(self, name: str) -> Optional[Dict[str, Any]]:
        """Get an inventory source by name.

        Args:
            name: Source name to look up.

        Returns:
            Source dictionary or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_sources WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return None

    def get_source_by_id(self, source_id: int) -> Optional[Dict[str, Any]]:
        """Get an inventory source by ID.

        Args:
            source_id: Source ID to look up.

        Returns:
            Source dictionary or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_sources WHERE id = ?", (source_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return None

    def list_sources(self) -> List[Dict[str, Any]]:
        """List all inventory sources.

        Returns:
            List of source dictionaries, ordered by creation date (newest first).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_sources ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def update_source_host_count(self, source_id: int, count: int) -> None:
        """Update the host count for a source.

        Args:
            source_id: Source ID to update.
            count: New host count.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE inventory_sources
            SET host_count = ?, updated_at = ?
            WHERE id = ?
        """, (count, datetime.now().isoformat(), source_id))

        conn.commit()
        conn.close()

    def delete_source(self, name: str) -> bool:
        """Delete an inventory source and its hosts.

        Args:
            name: Source name to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM inventory_sources WHERE name = ?", (name,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return False

        source_id = row[0]

        # Delete hosts from this source
        cursor.execute("DELETE FROM hosts_v2 WHERE source_id = ?", (source_id,))
        # Delete the source
        cursor.execute("DELETE FROM inventory_sources WHERE id = ?", (source_id,))

        conn.commit()
        conn.close()

        return True
