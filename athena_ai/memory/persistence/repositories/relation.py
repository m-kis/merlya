"""
Relation Repository Mixin - Manages host relationships.

Handles CRUD operations for host-to-host relations (dependencies, connections, etc.).
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


class RelationRepositoryMixin:
    """Mixin for host relation operations."""

    def _init_relation_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize host relations table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS host_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_host_id INTEGER NOT NULL,
                target_host_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                metadata TEXT,
                created_at TEXT NOT NULL,
                validated_by_user INTEGER DEFAULT 0,
                FOREIGN KEY (source_host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
                FOREIGN KEY (target_host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
                UNIQUE(source_host_id, target_host_id, relation_type)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_relations_source ON host_relations(source_host_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_relations_target ON host_relations(target_host_id)
        """)

    def add_relation(
        self,
        source_hostname: str,
        target_hostname: str,
        relation_type: str,
        confidence: float = 1.0,
        validated: bool = False,
        metadata: Optional[Dict] = None,
    ) -> Optional[int]:
        """Add a relation between two hosts.

        Args:
            source_hostname: Source host name.
            target_hostname: Target host name.
            relation_type: Type of relation (e.g., 'connects_to', 'depends_on').
            confidence: Confidence score (0.0 to 1.0).
            validated: Whether user has validated this relation.
            metadata: Optional metadata dictionary.

        Returns:
            Relation ID or None if hosts not found.
        """
        source_host = self.get_host_by_name(source_hostname)
        target_host = self.get_host_by_name(target_hostname)

        if not source_host or not target_host:
            return None

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO host_relations
                (source_host_id, target_host_id, relation_type, confidence, validated_by_user, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                source_host["id"],
                target_host["id"],
                relation_type,
                confidence,
                1 if validated else 0,
                json.dumps(metadata or {}),
                datetime.now().isoformat(),
            ))

            relation_id = cursor.lastrowid
            conn.commit()
            conn.close()

            return relation_id

        except sqlite3.IntegrityError:
            conn.close()
            return None

    def get_relations(
        self,
        hostname: Optional[str] = None,
        relation_type: Optional[str] = None,
        validated_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get host relations.

        If hostname is provided but not found, returns empty list (not all relations).

        Args:
            hostname: Optional hostname to filter relations by.
            relation_type: Optional relation type to filter by.
            validated_only: Only return user-validated relations.

        Returns:
            List of relation dictionaries.
        """
        # If hostname filter requested but host not found, return empty list
        host_id = None
        if hostname:
            host = self.get_host_by_name(hostname)
            if not host:
                return []
            host_id = host["id"]

        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT r.*, s.hostname as source_hostname, t.hostname as target_hostname
            FROM host_relations r
            JOIN hosts_v2 s ON r.source_host_id = s.id
            JOIN hosts_v2 t ON r.target_host_id = t.id
            WHERE 1=1
        """
        params = []

        if host_id is not None:
            query += " AND (r.source_host_id = ? OR r.target_host_id = ?)"
            params.extend([host_id, host_id])

        if relation_type:
            query += " AND r.relation_type = ?"
            params.append(relation_type)

        if validated_only:
            query += " AND r.validated_by_user = 1"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def validate_relation(self, relation_id: int) -> None:
        """Mark a relation as validated by user.

        Args:
            relation_id: Relation ID to validate.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE host_relations
            SET validated_by_user = 1
            WHERE id = ?
        """, (relation_id,))

        conn.commit()
        conn.close()

    def delete_relation(self, relation_id: int) -> bool:
        """Delete a relation.

        Args:
            relation_id: Relation ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM host_relations WHERE id = ?", (relation_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()
        return deleted
