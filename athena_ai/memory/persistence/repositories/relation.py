"""
Relation Repository Mixin - Manages host relationships.

Handles CRUD operations for host-to-host relations (dependencies, connections, etc.).
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BatchRelationResult:
    """Result of a batch relation insert operation.

    Attributes:
        saved_count: Number of relations successfully saved.
        skipped: List of (index, reason) tuples for skipped relations.
    """

    saved_count: int = 0
    skipped: List[Tuple[int, str]] = field(default_factory=list)


class RelationRepositoryMixin:
    """Mixin for host relation operations."""

    # Type stubs for methods provided by BaseRepository or other mixins
    @contextmanager
    def _connection(self, *, commit: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """Provided by BaseRepository."""
        raise NotImplementedError  # pragma: no cover
        yield  # type: ignore[misc]  # Generator requires yield

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Provided by BaseRepository."""
        raise NotImplementedError  # pragma: no cover

    def get_host_by_name(self, hostname: str) -> Optional[Dict[str, Any]]:
        """Provided by HostRepositoryMixin."""
        raise NotImplementedError  # pragma: no cover

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

    def _validate_relation_field(
        self, rel: Dict[str, Any], field_name: str, index: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """Validate a required string field in a relation dict.

        Args:
            rel: The relation dictionary.
            field_name: The field name to validate.
            index: The index of the relation in the batch (for error messages).

        Returns:
            Tuple of (validated_value, error_message). If validation succeeds,
            error_message is None. If validation fails, validated_value is None.
        """
        if field_name not in rel:
            return None, f"relation[{index}]: missing required field '{field_name}'"

        value = rel[field_name]
        if value is None:
            return None, f"relation[{index}]: '{field_name}' is None"

        if isinstance(value, str):
            if not value.strip():
                return None, f"relation[{index}]: '{field_name}' is empty string"
            return value.lower(), None

        # Try to convert to string if it's a reasonable type
        if isinstance(value, (int, float)):
            logger.warning(
                "relation[%d]: '%s' is %s, converting to string",
                index,
                field_name,
                type(value).__name__,
            )
            return str(value).lower(), None

        return None, (
            f"relation[{index}]: '{field_name}' must be a string, "
            f"got {type(value).__name__}"
        )

    def add_relations_batch(
        self,
        relations: List[Dict[str, Any]],
    ) -> BatchRelationResult:
        """Add multiple relations in a single transaction.

        Relations with invalid fields or whose source/target host does not exist
        in the database are skipped and recorded in the result. Partial saves may
        occur: some relations may be saved while others are skipped.

        Args:
            relations: List of relation dicts, each containing:
                - source_hostname: Source host name (required, must be str)
                - target_hostname: Target host name (required, must be str)
                - relation_type: Type of relation (required, must be str)
                - confidence: Optional confidence score (default 1.0)
                - validated: Optional bool (default False)
                - metadata: Optional metadata dict

        Returns:
            BatchRelationResult with saved_count and list of skipped relations.

        Raises:
            ValueError: If confidence is not between 0.0 and 1.0.
            sqlite3.Error: If a database error occurs (transaction is rolled back).
        """
        result = BatchRelationResult()

        if not relations:
            return result

        now = datetime.now().isoformat()

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            # Optimization: Pre-fetch all unique hostnames to avoid N+1 queries
            # Collect all unique hostnames from source and target fields
            all_hostnames = set()
            for rel in relations:
                source = rel.get("source_hostname")
                target = rel.get("target_hostname")
                if isinstance(source, str) and source.strip():
                    all_hostnames.add(source.lower())
                if isinstance(target, str) and target.strip():
                    all_hostnames.add(target.lower())

            # Fetch all host IDs in a single query using IN clause
            hostname_to_id = {}
            if all_hostnames:
                placeholders = ",".join("?" * len(all_hostnames))
                cursor.execute(
                    f"SELECT hostname, id FROM hosts_v2 WHERE hostname IN ({placeholders})",
                    list(all_hostnames),
                )
                hostname_to_id = {row[0]: row[1] for row in cursor.fetchall()}

            for idx, rel in enumerate(relations):
                # Validate source_hostname
                source_hostname, error = self._validate_relation_field(
                    rel, "source_hostname", idx
                )
                if error:
                    logger.warning("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

                # Validate target_hostname
                target_hostname, error = self._validate_relation_field(
                    rel, "target_hostname", idx
                )
                if error:
                    logger.warning("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

                # Validate relation_type
                relation_type, error = self._validate_relation_field(
                    rel, "relation_type", idx
                )
                if error:
                    logger.warning("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

                confidence = rel.get("confidence", 1.0)
                validated = rel.get("validated", False)
                metadata = rel.get("metadata")

                # Validate confidence
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    error = f"relation[{idx}]: confidence must be numeric, got {type(confidence).__name__}"
                    logger.warning("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

                if not (0.0 <= confidence <= 1.0):
                    error = f"relation[{idx}]: confidence must be between 0.0 and 1.0, got {confidence}"
                    logger.warning("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

                metadata_json = json.dumps(metadata or {})
                validated_int = 1 if validated else 0

                # Look up source host from pre-fetched map (avoids N+1 query)
                source_host_id = hostname_to_id.get(source_hostname)
                if source_host_id is None:
                    error = f"relation[{idx}]: source host '{source_hostname}' not found"
                    logger.debug("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

                # Look up target host from pre-fetched map (avoids N+1 query)
                target_host_id = hostname_to_id.get(target_hostname)
                if target_host_id is None:
                    error = f"relation[{idx}]: target host '{target_hostname}' not found"
                    logger.debug("Skipping relation: %s", error)
                    result.skipped.append((idx, error))
                    continue

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
                result.saved_count += 1

        return result
