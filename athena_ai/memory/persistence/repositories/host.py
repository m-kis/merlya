"""
Host Repository Mixin - Manages host entities with versioning.

Handles CRUD operations for hosts including version tracking for audit trails.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.core.exceptions import PersistenceError
from athena_ai.utils.logger import logger


@dataclass
class HostData:
    """Data container for host bulk imports."""

    hostname: str
    ip_address: Optional[str] = None
    aliases: Optional[List[str]] = None
    environment: Optional[str] = None
    groups: Optional[List[str]] = None
    role: Optional[str] = None
    service: Optional[str] = None
    ssh_port: Optional[int] = None
    metadata: Optional[Dict] = None


class HostRepositoryMixin:
    """Mixin for host operations with versioning support."""

    def _init_host_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize hosts and host versions tables."""
        # Hosts v2 table (main host storage)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hosts_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL UNIQUE,
                ip_address TEXT,
                aliases TEXT,
                environment TEXT,
                groups TEXT,
                role TEXT,
                service TEXT,
                ssh_port INTEGER DEFAULT 22,
                status TEXT DEFAULT 'unknown',
                source_id INTEGER,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES inventory_sources(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hosts_v2_hostname ON hosts_v2(hostname)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hosts_v2_environment ON hosts_v2(environment)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hosts_v2_source ON hosts_v2(source_id)
        """)

        # Host versions table (versioning)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS host_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                changes TEXT NOT NULL,
                changed_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                FOREIGN KEY (host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_host_versions_host ON host_versions(host_id, version)
        """)

    def add_host(
        self,
        hostname: str,
        ip_address: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        environment: Optional[str] = None,
        groups: Optional[List[str]] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        ssh_port: Optional[int] = None,
        source_id: Optional[int] = None,
        metadata: Optional[Dict] = None,
        changed_by: str = "system",
    ) -> int:
        """Add a new host or update if exists.

        Uses atomic upsert (INSERT ... ON CONFLICT DO UPDATE) to avoid
        TOCTOU race conditions between existence check and insert/update.

        Args:
            hostname: The hostname (will be lowercased).
            ip_address: Optional IP address.
            aliases: Optional list of hostname aliases.
            environment: Optional environment name (e.g., 'production').
            groups: Optional list of group names.
            role: Optional role name.
            service: Optional service name.
            ssh_port: Optional SSH port. If None, preserves existing value on
                update or uses database default (22) on insert.
            source_id: Optional inventory source ID.
            metadata: Optional metadata dictionary.
            changed_by: Who made the change (for versioning).

        Returns:
            The host ID (existing or newly created).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        hostname_lower = hostname.lower()

        # Serialize JSON fields (None if not provided, to let COALESCE preserve existing)
        aliases_json = json.dumps(aliases) if aliases is not None else None
        groups_json = json.dumps(groups) if groups is not None else None
        metadata_json = json.dumps(metadata) if metadata is not None else None

        # For new inserts, we need defaults for required JSON fields
        aliases_default = json.dumps([])
        groups_default = json.dumps([])
        metadata_default = json.dumps({})

        # Get old data for versioning (if host exists)
        cursor.execute("SELECT * FROM hosts_v2 WHERE hostname = ?", (hostname_lower,))
        existing_row = cursor.fetchone()
        old_data = self._host_row_to_dict(existing_row) if existing_row else None

        # Atomic upsert: INSERT or UPDATE in a single statement
        cursor.execute("""
            INSERT INTO hosts_v2
            (hostname, ip_address, aliases, environment, groups, role, service,
             ssh_port, status, source_id, metadata, created_at, updated_at)
            VALUES (?, ?, COALESCE(?, ?), ?, COALESCE(?, ?), ?, ?, COALESCE(?, 22), 'unknown', ?, COALESCE(?, ?), ?, ?)
            ON CONFLICT(hostname) DO UPDATE SET
                ip_address = COALESCE(excluded.ip_address, hosts_v2.ip_address),
                aliases = COALESCE(?, hosts_v2.aliases),
                environment = COALESCE(excluded.environment, hosts_v2.environment),
                groups = COALESCE(?, hosts_v2.groups),
                role = COALESCE(excluded.role, hosts_v2.role),
                service = COALESCE(excluded.service, hosts_v2.service),
                ssh_port = COALESCE(?, hosts_v2.ssh_port),
                source_id = COALESCE(excluded.source_id, hosts_v2.source_id),
                metadata = COALESCE(?, hosts_v2.metadata),
                updated_at = excluded.updated_at
            RETURNING id
        """, (
            # INSERT values
            hostname_lower,
            ip_address,
            aliases_json, aliases_default,
            environment,
            groups_json, groups_default,
            role,
            service,
            ssh_port,
            source_id,
            metadata_json, metadata_default,
            now,
            now,
            # ON CONFLICT UPDATE values
            aliases_json,
            groups_json,
            ssh_port,
            metadata_json,
        ))

        host_id = cursor.fetchone()[0]

        # Record version changes
        if old_data is None:
            self._add_host_version(cursor, host_id, {"action": "created"}, changed_by)
        else:
            changes = self._compute_changes(old_data, {
                "ip_address": ip_address,
                "aliases": aliases,
                "environment": environment,
                "groups": groups,
                "role": role,
                "service": service,
                "ssh_port": ssh_port,
                "metadata": metadata,
            })
            if changes:
                self._add_host_version(cursor, host_id, changes, changed_by)

        conn.commit()
        conn.close()

        return host_id

    def bulk_add_hosts(
        self,
        hosts: List[HostData],
        source_id: Optional[int] = None,
        changed_by: str = "system",
    ) -> int:
        """Add multiple hosts in a single transaction.

        All hosts are inserted atomically - if any insert fails, the entire
        transaction is rolled back and no hosts are persisted.

        Args:
            hosts: List of HostData objects to insert.
            source_id: Optional inventory source ID for all hosts.
            changed_by: Who made the change (for versioning).

        Returns:
            Number of hosts successfully added.

        Raises:
            PersistenceError: If any host insertion fails. The transaction
                is rolled back and no partial data is persisted.
        """
        if not hosts:
            return 0

        conn = self._get_connection()
        cursor = conn.cursor()
        added = 0

        try:
            for host in hosts:
                self._add_host_internal(
                    cursor=cursor,
                    hostname=host.hostname,
                    ip_address=host.ip_address,
                    aliases=host.aliases,
                    environment=host.environment,
                    groups=host.groups,
                    role=host.role,
                    service=host.service,
                    ssh_port=host.ssh_port,
                    source_id=source_id,
                    metadata=host.metadata,
                    changed_by=changed_by,
                )
                added += 1

            conn.commit()
            logger.debug(f"Bulk inserted {added} hosts in single transaction")
            return added

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Bulk host import failed after {added} hosts: {e}")
            raise PersistenceError(
                operation="bulk_add_hosts",
                reason=str(e),
                details={"hosts_attempted": len(hosts), "hosts_before_failure": added},
            ) from e
        finally:
            conn.close()

    def _add_host_internal(
        self,
        cursor: sqlite3.Cursor,
        hostname: str,
        ip_address: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        environment: Optional[str] = None,
        groups: Optional[List[str]] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        ssh_port: Optional[int] = None,
        source_id: Optional[int] = None,
        metadata: Optional[Dict] = None,
        changed_by: str = "system",
    ) -> int:
        """Internal host add without commit (for transactional batching).

        This is the core logic used by both add_host and bulk_add_hosts.
        Does NOT commit - caller is responsible for transaction management.

        Args:
            cursor: Database cursor (from caller's transaction).
            hostname: The hostname (will be lowercased).
            ip_address: Optional IP address.
            aliases: Optional list of hostname aliases.
            environment: Optional environment name.
            groups: Optional list of group names.
            role: Optional role name.
            service: Optional service name.
            ssh_port: Optional SSH port.
            source_id: Optional inventory source ID.
            metadata: Optional metadata dictionary.
            changed_by: Who made the change.

        Returns:
            The host ID (existing or newly created).
        """
        now = datetime.now().isoformat()
        hostname_lower = hostname.lower()

        # Serialize JSON fields
        aliases_json = json.dumps(aliases) if aliases is not None else None
        groups_json = json.dumps(groups) if groups is not None else None
        metadata_json = json.dumps(metadata) if metadata is not None else None

        # Defaults for new inserts
        aliases_default = json.dumps([])
        groups_default = json.dumps([])
        metadata_default = json.dumps({})

        # Get old data for versioning
        cursor.execute("SELECT * FROM hosts_v2 WHERE hostname = ?", (hostname_lower,))
        existing_row = cursor.fetchone()
        old_data = self._host_row_to_dict(existing_row) if existing_row else None

        # Atomic upsert
        cursor.execute("""
            INSERT INTO hosts_v2
            (hostname, ip_address, aliases, environment, groups, role, service,
             ssh_port, status, source_id, metadata, created_at, updated_at)
            VALUES (?, ?, COALESCE(?, ?), ?, COALESCE(?, ?), ?, ?, COALESCE(?, 22), 'unknown', ?, COALESCE(?, ?), ?, ?)
            ON CONFLICT(hostname) DO UPDATE SET
                ip_address = COALESCE(excluded.ip_address, hosts_v2.ip_address),
                aliases = COALESCE(?, hosts_v2.aliases),
                environment = COALESCE(excluded.environment, hosts_v2.environment),
                groups = COALESCE(?, hosts_v2.groups),
                role = COALESCE(excluded.role, hosts_v2.role),
                service = COALESCE(excluded.service, hosts_v2.service),
                ssh_port = COALESCE(?, hosts_v2.ssh_port),
                source_id = COALESCE(excluded.source_id, hosts_v2.source_id),
                metadata = COALESCE(?, hosts_v2.metadata),
                updated_at = excluded.updated_at
            RETURNING id
        """, (
            hostname_lower,
            ip_address,
            aliases_json, aliases_default,
            environment,
            groups_json, groups_default,
            role,
            service,
            ssh_port,
            source_id,
            metadata_json, metadata_default,
            now,
            now,
            aliases_json,
            groups_json,
            ssh_port,
            metadata_json,
        ))

        host_id = cursor.fetchone()[0]

        # Record version
        if old_data is None:
            self._add_host_version(cursor, host_id, {"action": "created"}, changed_by)
        else:
            changes = self._compute_changes(old_data, {
                "ip_address": ip_address,
                "aliases": aliases,
                "environment": environment,
                "groups": groups,
                "role": role,
                "service": service,
                "ssh_port": ssh_port,
                "metadata": metadata,
            })
            if changes:
                self._add_host_version(cursor, host_id, changes, changed_by)

        return host_id

    def _add_host_version(
        self,
        cursor: sqlite3.Cursor,
        host_id: int,
        changes: Dict,
        changed_by: str,
    ) -> None:
        """Add a version entry for a host.

        Args:
            cursor: Database cursor.
            host_id: Host ID to version.
            changes: Dictionary of changes made.
            changed_by: Who made the change.
        """
        cursor.execute(
            "SELECT COALESCE(MAX(version), 0) FROM host_versions WHERE host_id = ?",
            (host_id,)
        )
        current_version = cursor.fetchone()[0]
        new_version = current_version + 1

        cursor.execute("""
            INSERT INTO host_versions (host_id, version, changes, changed_by, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (host_id, new_version, json.dumps(changes), changed_by, datetime.now().isoformat()))

    def _compute_changes(self, old_data: Optional[Dict], new_data: Dict) -> Dict:
        """Compute changes between old and new data.

        Args:
            old_data: Previous host data.
            new_data: New host data.

        Returns:
            Dictionary of changed fields with old and new values.
        """
        changes = {}
        for key, new_value in new_data.items():
            if new_value is not None:
                old_value = old_data.get(key) if isinstance(old_data, dict) else None
                if old_value != new_value:
                    changes[key] = {"old": old_value, "new": new_value}
        return changes

    def get_host_by_id(self, host_id: int) -> Optional[Dict[str, Any]]:
        """Get a host by ID.

        Args:
            host_id: Host ID to look up.

        Returns:
            Host dictionary or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM hosts_v2 WHERE id = ?", (host_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._host_row_to_dict(row)
        return None

    def get_host_by_name(self, hostname: str) -> Optional[Dict[str, Any]]:
        """Get a host by hostname (case-insensitive).

        Also searches aliases if exact hostname match not found.

        Args:
            hostname: Hostname to look up.

        Returns:
            Host dictionary or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # First try exact match
        cursor.execute("SELECT * FROM hosts_v2 WHERE hostname = ?", (hostname.lower(),))
        row = cursor.fetchone()

        # If not found, try alias match
        if not row:
            cursor.execute("SELECT * FROM hosts_v2 WHERE aliases LIKE ?", (f'%"{hostname.lower()}"%',))
            row = cursor.fetchone()

        conn.close()

        if row:
            return self._host_row_to_dict(row)
        return None

    def search_hosts(
        self,
        pattern: Optional[str] = None,
        environment: Optional[str] = None,
        group: Optional[str] = None,
        source_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: Optional[int] = 100,
    ) -> List[Dict[str, Any]]:
        """Search hosts with various filters.

        Args:
            pattern: Search pattern for hostname, aliases, or IP address.
            environment: Filter by environment.
            group: Filter by group membership.
            source_id: Filter by source ID.
            status: Filter by status.
            limit: Maximum results to return. None means unlimited.

        Returns:
            List of host dictionaries matching the filters.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM hosts_v2 WHERE 1=1"
        params: list = []

        if pattern:
            query += " AND (hostname LIKE ? OR aliases LIKE ? OR ip_address LIKE ?)"
            pattern_like = f"%{pattern.lower()}%"
            params.extend([pattern_like, pattern_like, pattern_like])

        if environment:
            query += " AND environment = ?"
            params.append(environment)

        if group:
            query += " AND groups LIKE ?"
            params.append(f'%"{group}"%')

        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY hostname"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._host_row_to_dict(row) for row in rows]

    def get_all_hosts(self) -> List[Dict[str, Any]]:
        """Get all hosts without any limit.

        Returns:
            List of all host dictionaries.
        """
        return self.search_hosts(limit=None)

    def update_host_status(self, host_id: int, status: str) -> None:
        """Update host status (online, offline, unknown).

        Args:
            host_id: Host ID to update.
            status: New status value.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE hosts_v2
            SET status = ?, updated_at = ?
            WHERE id = ?
        """, (status, datetime.now().isoformat(), host_id))

        conn.commit()
        conn.close()

    def delete_host(self, hostname: str) -> bool:
        """Delete a host by hostname.

        Args:
            hostname: Hostname to delete.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM hosts_v2 WHERE hostname = ?", (hostname.lower(),))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()

        return deleted

    def get_host_versions(self, host_id: int) -> List[Dict[str, Any]]:
        """Get version history for a host.

        Args:
            host_id: Host ID to get versions for.

        Returns:
            List of version dictionaries, newest first.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM host_versions
            WHERE host_id = ?
            ORDER BY version DESC
        """, (host_id,))
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def _host_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a host row to dictionary with JSON parsing.

        Args:
            row: Database row.

        Returns:
            Host dictionary with parsed JSON fields.
        """
        d = dict(row)
        # Parse JSON fields with appropriate defaults
        for field in ["aliases", "groups"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
            else:
                d[field] = []
        # Metadata defaults to empty dict
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        else:
            d["metadata"] = {}
        return d
