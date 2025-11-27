"""
Local Context Repository Mixin - Manages local machine context.

Handles persistence of local machine state (environment, tools, services, etc.).
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional


class LocalContextRepositoryMixin:
    """Mixin for local context operations."""

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
            Dictionary with categories as keys and their data as values,
            or None if no context exists.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM local_context ORDER BY category, key")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        context: Dict[str, Any] = {}
        scanned_at = None

        for row in rows:
            row_dict = self._row_to_dict(row)
            category = row_dict["category"]
            key = row_dict["key"]
            value = row_dict["value"]

            # Try to parse JSON values
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass

            if category not in context:
                context[category] = {}
            context[category][key] = value

            # Track the most recent update as scanned_at
            if scanned_at is None or row_dict["updated_at"] > scanned_at:
                scanned_at = row_dict["updated_at"]

        context["scanned_at"] = scanned_at
        return context

    def save_local_context(self, context: Dict[str, Any]) -> None:
        """Save local context to database (atomic operation).

        Args:
            context: Dictionary with categories as keys and their data as values.

        Raises:
            Exception: If save operation fails (transaction rolled back).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            # Start explicit transaction
            cursor.execute("BEGIN IMMEDIATE")

            # Clear existing context
            cursor.execute("DELETE FROM local_context")

            # Insert new context
            for category, data in context.items():
                if category == "scanned_at":
                    continue

                if isinstance(data, dict):
                    for key, value in data.items():
                        value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                        cursor.execute("""
                            INSERT INTO local_context (category, key, value, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (category, key, value_str, now, now))
                else:
                    value_str = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
                    cursor.execute("""
                        INSERT INTO local_context (category, key, value, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (category, "value", value_str, now, now))

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def has_local_context(self) -> bool:
        """Check if local context exists.

        Returns:
            True if context exists, False otherwise.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM local_context")
        count = cursor.fetchone()[0]
        conn.close()

        return count > 0
