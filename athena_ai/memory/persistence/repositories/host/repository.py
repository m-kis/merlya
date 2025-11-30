"""
Host Repository Mixin.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.core.exceptions import PersistenceError
from athena_ai.utils.logger import logger

from .converters import host_row_to_dict, version_row_to_dict
from .models import HostData
from .schema import init_host_tables
from .versioning import add_host_version, compute_changes


class HostRepositoryMixin:
    """Mixin for host operations with versioning support."""

    # Class-level cache for SQLite version check (shared across instances)
    _sqlite_supports_json_each: Optional[bool] = None

    def _init_host_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize hosts and host versions tables."""
        init_host_tables(cursor)

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
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            return self._add_host_internal(
                cursor=cursor,
                hostname=hostname,
                ip_address=ip_address,
                aliases=aliases,
                environment=environment,
                groups=groups,
                role=role,
                service=service,
                ssh_port=ssh_port,
                source_id=source_id,
                metadata=metadata,
                changed_by=changed_by,
            )

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

        added = 0
        try:
            with self._connection(commit=True) as conn:
                cursor = conn.cursor()
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

            logger.debug(f"Bulk inserted {added} hosts in single transaction")
            return added

        except sqlite3.Error as e:
            logger.error(f"Bulk host import failed after {added} hosts: {e}")
            raise PersistenceError(
                operation="bulk_add_hosts",
                reason=str(e),
                details={"hosts_attempted": len(hosts), "hosts_before_failure": added},
            ) from e

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

        NULL Handling Semantics:
            - On INSERT: NULL fields get defaults (empty list/dict, or DB default for ssh_port=22)
            - On UPDATE: NULL fields are PRESERVED (existing value is kept, not cleared)
            - To clear a field, use explicit empty values: [] for lists, {} for dicts, "" for strings

        Args:
            cursor: Database cursor (from caller's transaction).
            hostname: The hostname (will be lowercased).
            ip_address: Optional IP address. None preserves existing on update.
            aliases: Optional list of hostname aliases. None preserves existing on update.
            environment: Optional environment name. None preserves existing on update.
            groups: Optional list of group names. None preserves existing on update.
            role: Optional role name. None preserves existing on update.
            service: Optional service name. None preserves existing on update.
            ssh_port: Optional SSH port. None preserves existing on update (default 22 on insert).
            source_id: Optional inventory source ID. None preserves existing on update.
            metadata: Optional metadata dictionary. None preserves existing on update.
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

        # Atomic upsert with insert/update detection via changes() function
        # We use SQLite's changes() after the upsert to detect if it was an insert or update.
        # This avoids the TOCTOU race condition of a separate SELECT before INSERT.
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
            RETURNING id, (
                SELECT COUNT(*) FROM hosts_v2 h2
                WHERE h2.hostname = ? AND h2.created_at < ?
            ) as existed_before
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
            hostname_lower,
            now,
        ))

        result = cursor.fetchone()
        host_id = result[0]
        was_update = result[1] > 0  # existed_before > 0 means this was an update

        # Record version based on actual operation type
        if not was_update:
            add_host_version(cursor, host_id, {"action": "created"}, changed_by)
        else:
            # Fetch current state to compute accurate changes
            # This is safe because we're still in the same transaction after our upsert
            cursor.execute("SELECT * FROM hosts_v2 WHERE id = ?", (host_id,))
            current_row = cursor.fetchone()
            current_data = host_row_to_dict(current_row)

            # Compute what actually changed (comparing input vs what was there before)
            # Note: We compare against current_data which now has the merged values
            changes = compute_changes(current_data, {
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
                add_host_version(cursor, host_id, changes, changed_by)

        return host_id

    def get_host_by_id(self, host_id: int) -> Optional[Dict[str, Any]]:
        """Get a host by ID.

        Args:
            host_id: Host ID to look up.

        Returns:
            Host dictionary or None if not found.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM hosts_v2 WHERE id = ?", (host_id,))
            row = cursor.fetchone()

        if row:
            return host_row_to_dict(row)
        return None

    def get_host_by_name(self, hostname: str) -> Optional[Dict[str, Any]]:
        """Get a host by hostname (case-insensitive).

        Also searches aliases if exact hostname match not found.

        Args:
            hostname: Hostname to look up.

        Returns:
            Host dictionary or None if not found.
        """
        hostname_lower = hostname.lower()

        with self._connection() as conn:
            cursor = conn.cursor()
            # First try exact match
            cursor.execute("SELECT * FROM hosts_v2 WHERE hostname = ?", (hostname_lower,))
            row = cursor.fetchone()

            # If not found, try alias match with exact JSON array element matching
            if not row:
                row = self._find_host_by_alias(cursor, hostname_lower)

        if row:
            return host_row_to_dict(row)
        return None

    def _check_sqlite_json_each_support(self, cursor: sqlite3.Cursor) -> bool:
        """Check if SQLite supports json_each (version >= 3.9.0).

        Result is cached at class level to avoid repeated version checks.

        Args:
            cursor: Database cursor.

        Returns:
            True if json_each is supported, False otherwise.
        """
        if HostRepositoryMixin._sqlite_supports_json_each is not None:
            return HostRepositoryMixin._sqlite_supports_json_each

        cursor.execute("SELECT sqlite_version()")
        version_str = cursor.fetchone()[0]
        # Parse version safely: pad to 3 parts, handle non-numeric components
        raw_parts = version_str.split(".")[:3]
        while len(raw_parts) < 3:
            raw_parts.append("0")
        version_parts = []
        for p in raw_parts:
            try:
                version_parts.append(int(p))
            except ValueError:
                version_parts.append(0)
        sqlite_version = version_parts[0] * 1000000 + version_parts[1] * 1000 + version_parts[2]

        HostRepositoryMixin._sqlite_supports_json_each = sqlite_version >= 3009000
        return HostRepositoryMixin._sqlite_supports_json_each

    def _find_host_by_alias(
        self, cursor: sqlite3.Cursor, alias: str
    ) -> Optional[sqlite3.Row]:
        """Find a host by exact alias match.

        Uses json_each() for SQLite >= 3.9, falls back to Python-side
        JSON parsing for older versions.

        Args:
            cursor: Database cursor.
            alias: Alias to search for (already lowercased).

        Returns:
            Host row or None if not found.
        """
        if self._check_sqlite_json_each_support(cursor):
            # SQLite >= 3.9: Use json_each for exact array element matching
            cursor.execute("""
                SELECT h.* FROM hosts_v2 h, json_each(h.aliases) AS alias
                WHERE alias.value = ?
                LIMIT 1
            """, (alias,))
            return cursor.fetchone()
        else:
            # Fallback for older SQLite: fetch candidates and check in Python
            # Use LIKE as a pre-filter to avoid scanning all rows
            cursor.execute(
                "SELECT * FROM hosts_v2 WHERE aliases LIKE ?",
                (f'%"{alias}"%',)
            )
            for row in cursor.fetchall():
                try:
                    aliases_list = json.loads(row["aliases"]) if row["aliases"] else []
                    if alias in aliases_list:
                        return row
                except (json.JSONDecodeError, TypeError):
                    continue
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
        query = "SELECT * FROM hosts_v2 WHERE 1=1"
        params: list = []

        if pattern:
            # Use LOWER() for case-insensitive matching on aliases (hostname is already lowercase)
            query += " AND (hostname LIKE ? OR LOWER(aliases) LIKE ? OR ip_address LIKE ?)"
            pattern_like = f"%{pattern.lower()}%"
            params.extend([pattern_like, pattern_like, pattern_like])

        if environment:
            query += " AND environment = ?"
            params.append(environment)

        if group:
            # Escape SQL wildcard characters AND JSON special characters for safe matching
            # Order matters: escape backslash first, then quotes, then SQL wildcards
            escaped_group = (
                group
                .replace("\\", "\\\\")  # Escape backslashes first
                .replace('"', '\\"')     # Escape JSON quotes
                .replace("%", "\\%")     # Escape SQL LIKE wildcard
                .replace("_", "\\_")     # Escape SQL LIKE single-char wildcard
            )
            query += " AND groups LIKE ? ESCAPE '\\'"
            params.append(f'%"{escaped_group}"%')

        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY hostname"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        return [host_row_to_dict(row) for row in rows]

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
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE hosts_v2
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (status, datetime.now().isoformat(), host_id))

    def delete_host(
        self,
        hostname: str,
        deleted_by: str = "system",
        reason: Optional[str] = None,
    ) -> bool:
        """Delete a host by hostname.

        Creates a permanent audit record in the host_deletions table before deletion.
        This record captures the full host state at the time of deletion along with
        deletion metadata (who deleted it and why). The audit record persists even
        after the host and its version history are removed.

        Args:
            hostname: Hostname to delete.
            deleted_by: Who is performing the deletion (for audit trail).
            reason: Optional reason for deletion (for audit trail).

        Returns:
            True if deleted, False if not found.
        """
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            # Fetch the host to delete (for audit trail)
            cursor.execute("SELECT * FROM hosts_v2 WHERE hostname = ?", (hostname.lower(),))
            row = cursor.fetchone()

            if not row:
                return False

            # Extract host data for audit record
            host_data = host_row_to_dict(row)
            host_id = host_data["id"]

            # Insert permanent deletion audit record
            # Note: We store the raw JSON strings (aliases, groups, metadata) as-is
            cursor.execute("""
                INSERT INTO host_deletions
                (host_id, hostname, ip_address, aliases, environment, groups,
                 role, service, ssh_port, status, metadata, deleted_by,
                 deletion_reason, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                host_id,
                host_data["hostname"],
                host_data.get("ip_address"),
                json.dumps(host_data.get("aliases", [])),
                host_data.get("environment"),
                json.dumps(host_data.get("groups", [])),
                host_data.get("role"),
                host_data.get("service"),
                host_data.get("ssh_port"),
                host_data.get("status"),
                json.dumps(host_data.get("metadata", {})),
                deleted_by,
                reason,
                datetime.now().isoformat(),
            ))

            # Now perform the actual deletion
            # This will CASCADE delete all host_versions entries
            cursor.execute("DELETE FROM hosts_v2 WHERE hostname = ?", (hostname.lower(),))
            return cursor.rowcount > 0

    def get_host_versions(self, host_id: int) -> List[Dict[str, Any]]:
        """Get version history for a host.

        Args:
            host_id: Host ID to get versions for.

        Returns:
            List of version dictionaries, newest first.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM host_versions
                WHERE host_id = ?
                ORDER BY version DESC
            """, (host_id,))
            rows = cursor.fetchall()

        return [version_row_to_dict(row) for row in rows]
