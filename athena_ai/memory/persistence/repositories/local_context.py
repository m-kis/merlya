"""
Local Context Repository Mixin - Manages local machine context.

Handles persistence of local machine state (environment, tools, services, etc.).
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional

# Reserved key for metadata to avoid collision with user categories
_METADATA_KEY = "_metadata"

if TYPE_CHECKING:
    pass  # Reserved for future type imports


class LocalContextRepositoryMixin:
    """
    Mixin for local context operations.

    This mixin requires the following methods from the including class
    (typically provided by BaseRepository):
        - _connection(commit: bool = False) -> ContextManager[sqlite3.Connection]
        - _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]

    Data Model:
        Context is stored as category/key/value triplets in SQLite.
        The structure returned by get_local_context is:
        {
            "_metadata": {"scanned_at": "ISO timestamp"},
            "category1": {"key1": value1, "key2": value2, ...},
            "category2": {...},
            ...
        }

        All values are JSON-serialized for storage to preserve type information
        (booleans, numbers, None are preserved, not converted to strings).

    Reserved Keys:
        - "_metadata": Used for storing metadata (e.g., scanned_at timestamp).
          This key is stripped during save and regenerated during get.
        - "_value": Used internally to store non-dict category values.
          If you save {"category": "string_value"}, it becomes
          {"category": {"_value": "string_value"}} on retrieval.
    """

    # Type stubs for methods provided by BaseRepository
    # These are defined here for mypy, actual implementation is in BaseRepository
    @contextmanager
    def _connection(self, *, commit: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """Provided by BaseRepository."""
        raise NotImplementedError  # pragma: no cover

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Provided by BaseRepository."""
        raise NotImplementedError  # pragma: no cover

    def _init_local_context_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize local context table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS local_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(category, key)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_local_context_category ON local_context(category)
        """)

    def get_local_context(self) -> Optional[Dict[str, Any]]:
        """Get the full local context.

        Returns:
            Dictionary with structure:
            {
                "_metadata": {"scanned_at": "ISO timestamp"},
                "category1": {"key1": value1, ...},
                ...
            }
            Returns None if no context exists.

        Note:
            Uses _row_to_dict from BaseRepository for row conversion.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM local_context ORDER BY category, key")
            rows = cursor.fetchall()

        if not rows:
            return None

        context: Dict[str, Any] = {}
        scanned_at = None

        for row in rows:
            row_dict = self._row_to_dict(row)
            category = row_dict["category"]
            key = row_dict["key"]
            value = row_dict["value"]

            # All values are JSON-serialized, decode them
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                # Fallback for legacy data that wasn't JSON-encoded
                pass

            if category not in context:
                context[category] = {}
            context[category][key] = value

            # Track the most recent update as scanned_at
            if scanned_at is None or row_dict["updated_at"] > scanned_at:
                scanned_at = row_dict["updated_at"]

        # Store metadata in reserved key to avoid collision with user categories
        context[_METADATA_KEY] = {"scanned_at": scanned_at}
        return context

    def save_local_context(self, context: Dict[str, Any]) -> None:
        """Save local context to database (atomic operation).

        Args:
            context: Dictionary with categories as keys and their data as values.
                The "_metadata" key is reserved and will be skipped during save.
                Each category should be a dict with key/value pairs.

        Raises:
            sqlite3.Error: If save operation fails (transaction rolled back).

        Note:
            All values are JSON-serialized to preserve type information.
            This ensures round-trip consistency: save(x) followed by get()
            returns the same data types as x.
        """
        now = datetime.now().isoformat()

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            # Clear existing context
            cursor.execute("DELETE FROM local_context")

            # Insert new context
            for category, data in context.items():
                # Skip reserved metadata key
                if category == _METADATA_KEY:
                    continue

                # Handle dict categories (the expected case)
                if isinstance(data, dict):
                    for key, value in data.items():
                        # Always JSON-serialize to preserve types
                        value_str = json.dumps(value)
                        cursor.execute("""
                            INSERT INTO local_context (category, key, value, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (category, key, value_str, now, now))
                else:
                    # Non-dict values are stored with a single "_value" key
                    # This maintains round-trip consistency
                    value_str = json.dumps(data)
                    cursor.execute("""
                        INSERT INTO local_context (category, key, value, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (category, "_value", value_str, now, now))

    def has_local_context(self) -> bool:
        """Check if local context exists.

        Returns:
            True if context exists, False otherwise.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM local_context")
            count = cursor.fetchone()[0]

        return count > 0
