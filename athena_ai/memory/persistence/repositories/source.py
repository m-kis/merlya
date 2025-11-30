"""
Source Repository Mixin - Manages inventory sources.

Handles CRUD operations for inventory sources (manual, file imports, API, etc.).
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


class SourceRepositoryMixin:
    """Mixin for inventory source operations.

    This mixin requires the following methods from the including class:
        - _get_connection() -> sqlite3.Connection
        - _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]
    """

    # Type declarations for methods provided by BaseRepository
    # These are defined here for type checking purposes only.
    # Actual implementations come from BaseRepository.
    if False:  # TYPE_CHECKING equivalent that doesn't require import
        _get_connection: Any
        _row_to_dict: Any

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
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO inventory_sources
                (name, source_type, file_path, import_method, host_count, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """, (name, source_type, file_path, import_method, now, now, json.dumps(metadata or {})))

            source_id = cursor.lastrowid
            conn.commit()
            return source_id
        except sqlite3.IntegrityError as e:
            # Rollback immediately to clear the failed transaction state
            conn.rollback()

            error_msg = str(e)
            # Only treat as name collision if it's specifically the UNIQUE constraint on name
            # SQLite format: "UNIQUE constraint failed: inventory_sources.name"
            is_name_unique_violation = (
                "UNIQUE constraint failed" in error_msg
                and "inventory_sources.name" in error_msg
            )
            if is_name_unique_violation:
                # Source with this name already exists, return existing ID
                # Now safe to query after rollback cleared the failed transaction
                cursor.execute("SELECT id FROM inventory_sources WHERE name = ?", (name,))
                row = cursor.fetchone()
                if row:
                    return row[0]
                # Concurrent delete occurred - re-raise for caller
                raise ValueError(f"Source '{name}' was deleted during creation") from e
            # Different IntegrityError - re-raise so caller sees the actual constraint failure
            raise
        finally:
            conn.close()

    def get_source(self, name: str) -> Optional[Dict[str, Any]]:
        """Get an inventory source by name.

        Args:
            name: Source name to look up.

        Returns:
            Source dictionary or None if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventory_sources WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
        finally:
            conn.close()

    def get_source_by_id(self, source_id: int) -> Optional[Dict[str, Any]]:
        """Get an inventory source by ID.

        Args:
            source_id: Source ID to look up.

        Returns:
            Source dictionary or None if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventory_sources WHERE id = ?", (source_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
        finally:
            conn.close()

    def list_sources(self) -> List[Dict[str, Any]]:
        """List all inventory sources.

        Returns:
            List of source dictionaries, ordered by creation date (newest first).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventory_sources ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def update_source_host_count(self, source_id: int, count: int) -> None:
        """Update the host count for a source.

        Args:
            source_id: Source ID to update.
            count: New host count.

        Raises:
            ValueError: If count is negative.
            SourceNotFoundError: If source_id doesn't exist.
        """
        if count < 0:
            raise ValueError("count must be non-negative")

        from athena_ai.core.exceptions import SourceNotFoundError

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE inventory_sources
                SET host_count = ?, updated_at = ?
                WHERE id = ?
            """, (count, datetime.now().isoformat(), source_id))

            if cursor.rowcount == 0:
                raise SourceNotFoundError(source_id)

            conn.commit()
        except SourceNotFoundError:
            # Re-raise business logic errors without rollback
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_source(self, name: str) -> bool:
        """Delete an inventory source and its hosts.

        Associated hosts are automatically deleted via ON DELETE CASCADE
        on the hosts_v2.source_id foreign key constraint.

        Args:
            name: Source name to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM inventory_sources WHERE name = ?", (name,))
            row = cursor.fetchone()

            if not row:
                logger.debug(f"Source '{name}' not found for deletion")
                return False

            source_id = row[0]

            # Delete the source (hosts cascade-deleted via FK constraint)
            cursor.execute("DELETE FROM inventory_sources WHERE id = ?", (source_id,))

            if cursor.rowcount == 0:
                conn.rollback()
                logger.debug(f"Source '{name}' (id={source_id}) was concurrently deleted")
                return False

            conn.commit()
            logger.info(f"Deleted source '{name}' (id={source_id})")
            return True
        except sqlite3.Error as e:
            logger.error(f"Database error deleting source '{name}': {e}")
            if conn:
                conn.rollback()
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting source '{name}': {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
