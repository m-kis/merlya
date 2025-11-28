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

    def _parse_metadata(self, metadata_str: Optional[str]) -> Dict[str, Any]:
        """Parse metadata JSON string to dict.

        Args:
            metadata_str: JSON string or None.

        Returns:
            Parsed dict, or empty dict on null/empty/error.
        """
        if not metadata_str:
            return {}
        try:
            return json.loads(metadata_str)
        except (json.JSONDecodeError, TypeError):
            return {}

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
                updated_at TEXT,
                validated_by_user INTEGER DEFAULT 0,
                FOREIGN KEY (source_host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
                FOREIGN KEY (target_host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
                UNIQUE(source_host_id, target_host_id, relation_type)
            )
        """)
        # Add updated_at column if missing (migration for existing databases)
        cursor.execute("PRAGMA table_info(host_relations)")
        columns = [row[1] for row in cursor.fetchall()]
        if "updated_at" not in columns:
            cursor.execute("ALTER TABLE host_relations ADD COLUMN updated_at TEXT")
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

        Raises:
            ValueError: If confidence is not between 0.0 and 1.0.
        """
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")

        now = datetime.now().isoformat()
        metadata_json = json.dumps(metadata or {})
        validated_int = 1 if validated else 0
        source_hostname_lower = source_hostname.lower()
        target_hostname_lower = target_hostname.lower()

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            # Look up hosts inside the transaction to avoid TOCTOU race condition
            cursor.execute(
                "SELECT id FROM hosts_v2 WHERE hostname = ?", (source_hostname_lower,)
            )
            source_row = cursor.fetchone()
            if not source_row:
                return None
            source_host_id = source_row[0]

            cursor.execute(
                "SELECT id FROM hosts_v2 WHERE hostname = ?", (target_hostname_lower,)
            )
            target_row = cursor.fetchone()
            if not target_row:
                return None
            target_host_id = target_row[0]

            try:
                cursor.execute("""
                    INSERT INTO host_relations
                    (source_host_id, target_host_id, relation_type, confidence, validated_by_user, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_host_id, target_host_id, relation_type) DO UPDATE SET
                        confidence = excluded.confidence,
                        validated_by_user = excluded.validated_by_user,
                        metadata = excluded.metadata,
                        updated_at = ?
                """, (
                    source_host_id,
                    target_host_id,
                    relation_type,
                    confidence,
                    validated_int,
                    metadata_json,
                    now,
                    now,  # updated_at for the ON CONFLICT case
                ))
            except sqlite3.IntegrityError:
                # Foreign key violation - host was deleted between lookup and insert
                return None

            # Get the id - either newly inserted or existing row that was updated
            if cursor.lastrowid:
                relation_id = cursor.lastrowid
            else:
                # Row was updated, fetch the existing id
                cursor.execute("""
                    SELECT id FROM host_relations
                    WHERE source_host_id = ? AND target_host_id = ? AND relation_type = ?
                """, (source_host_id, target_host_id, relation_type))
                row = cursor.fetchone()
                relation_id = row[0] if row else None

        return relation_id

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

        query = """
            SELECT r.*, s.hostname as source_hostname, t.hostname as target_hostname
            FROM host_relations r
            JOIN hosts_v2 s ON r.source_host_id = s.id
            JOIN hosts_v2 t ON r.target_host_id = t.id
            WHERE 1=1
        """
        params: list = []

        if host_id is not None:
            query += " AND (r.source_host_id = ? OR r.target_host_id = ?)"
            params.extend([host_id, host_id])

        if relation_type:
            query += " AND r.relation_type = ?"
            params.append(relation_type)

        if validated_only:
            query += " AND r.validated_by_user = 1"

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        results = []
        for row in rows:
            row_dict = self._row_to_dict(row)
            row_dict["metadata"] = self._parse_metadata(row_dict.get("metadata"))
            results.append(row_dict)
        return results

    def validate_relation(self, relation_id: int) -> None:
        """Mark a relation as validated by user.

        Args:
            relation_id: Relation ID to validate.
        """
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE host_relations
                SET validated_by_user = 1
                WHERE id = ?
            """, (relation_id,))

    def delete_relation(self, relation_id: int) -> bool:
        """Delete a relation.

        Args:
            relation_id: Relation ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM host_relations WHERE id = ?", (relation_id,))
            return cursor.rowcount > 0

    def add_relations_batch(
        self,
        relations: List[Dict[str, Any]],
    ) -> int:
        """Add multiple relations in a single transaction.

        Relations whose source or target host does not exist in the database
        are silently skipped. Partial saves may occur: some relations may be
        saved while others are skipped due to missing hosts.

        Args:
            relations: List of relation dicts, each containing:
                - source_hostname: Source host name
                - target_hostname: Target host name
                - relation_type: Type of relation
                - confidence: Optional confidence score (default 1.0)
                - validated: Optional bool (default False)
                - metadata: Optional metadata dict

        Returns:
            Number of relations actually saved (excludes skipped relations).

        Raises:
            ValueError: If required fields are missing or confidence is not
                between 0.0 and 1.0.
            sqlite3.Error: If a database error occurs (transaction is rolled back).
        """
        if not relations:
            return 0

        now = datetime.now().isoformat()
        saved_count = 0

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            for rel in relations:
                required_fields = ["source_hostname", "target_hostname", "relation_type"]
                missing = [f for f in required_fields if f not in rel]
                if missing:
                    raise ValueError(f"Missing required fields: {missing}")

                source_hostname = rel["source_hostname"].lower()
                target_hostname = rel["target_hostname"].lower()
                relation_type = rel["relation_type"]
                confidence = rel.get("confidence", 1.0)
                validated = rel.get("validated", False)
                metadata = rel.get("metadata")

                if not (0.0 <= confidence <= 1.0):
                    raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence}")

                metadata_json = json.dumps(metadata or {})
                validated_int = 1 if validated else 0

                # Look up source host
                cursor.execute(
                    "SELECT id FROM hosts_v2 WHERE hostname = ?", (source_hostname,)
                )
                source_row = cursor.fetchone()
                if not source_row:
                    # Skip relations where host doesn't exist
                    continue
                source_host_id = source_row[0]

                # Look up target host
                cursor.execute(
                    "SELECT id FROM hosts_v2 WHERE hostname = ?", (target_hostname,)
                )
                target_row = cursor.fetchone()
                if not target_row:
                    # Skip relations where host doesn't exist
                    continue
                target_host_id = target_row[0]

                cursor.execute("""
                    INSERT INTO host_relations
                    (source_host_id, target_host_id, relation_type, confidence, validated_by_user, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_host_id, target_host_id, relation_type) DO UPDATE SET
                        confidence = excluded.confidence,
                        validated_by_user = excluded.validated_by_user,
                        metadata = excluded.metadata,
                        updated_at = ?
                """, (
                    source_host_id,
                    target_host_id,
                    relation_type,
                    confidence,
                    validated_int,
                    metadata_json,
                    now,
                    now,
                ))
                saved_count += 1

        return saved_count
