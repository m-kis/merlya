"""
Inventory Repository - Unified persistence for inventory v2.

Manages:
- Hosts with versioning
- Inventory sources
- Host relations
- Scan cache
- Local context
- Snapshots
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


class InventoryRepository:
    """
    Repository for the new inventory system.

    Provides CRUD operations for:
    - Hosts (with versioning)
    - Inventory sources
    - Host relations
    - Scan cache
    - Local machine context
    - Inventory snapshots
    """

    _instance: Optional["InventoryRepository"] = None

    def __new__(cls, db_path: Optional[str] = None):
        """Singleton pattern for repository."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        """Initialize repository with database path."""
        if self._initialized:
            return

        if db_path:
            self.db_path = db_path
        else:
            athena_dir = Path.home() / ".athena"
            athena_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(athena_dir / "inventory.db")

        self._init_tables()
        self._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_tables(self):
        """Initialize all database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Inventory sources table
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

        # Inventory snapshots table
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

        # Host relations table
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

        # Scan cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                scan_type TEXT NOT NULL,
                data TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
                UNIQUE(host_id, scan_type)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_cache_host ON scan_cache(host_id, scan_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_cache_expires ON scan_cache(expires_at)
        """)

        # Local context table
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

        conn.commit()
        conn.close()
        logger.debug(f"Inventory database initialized at {self.db_path}")

    # ==================== Inventory Sources ====================

    def add_source(
        self,
        name: str,
        source_type: str,
        file_path: Optional[str] = None,
        import_method: str = "manual",
        metadata: Optional[Dict] = None,
    ) -> int:
        """Add a new inventory source."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO inventory_sources
            (name, source_type, file_path, import_method, host_count, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
        """, (name, source_type, file_path, import_method, now, now, json.dumps(metadata or {})))

        source_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Added inventory source: {name} (type: {source_type})")
        return source_id

    def get_source(self, name: str) -> Optional[Dict]:
        """Get an inventory source by name."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_sources WHERE name = ?", (name,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return None

    def get_source_by_id(self, source_id: int) -> Optional[Dict]:
        """Get an inventory source by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_sources WHERE id = ?", (source_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_dict(row)
        return None

    def list_sources(self) -> List[Dict]:
        """List all inventory sources."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM inventory_sources ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def update_source_host_count(self, source_id: int, count: int):
        """Update the host count for a source."""
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
        """Delete an inventory source and its hosts."""
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

        logger.info(f"Deleted inventory source: {name}")
        return True

    # ==================== Hosts ====================

    def add_host(
        self,
        hostname: str,
        ip_address: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        environment: Optional[str] = None,
        groups: Optional[List[str]] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        ssh_port: int = 22,
        source_id: Optional[int] = None,
        metadata: Optional[Dict] = None,
        changed_by: str = "system",
    ) -> int:
        """Add a new host or update if exists."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # Check if host exists
        cursor.execute("SELECT id FROM hosts_v2 WHERE hostname = ?", (hostname.lower(),))
        existing = cursor.fetchone()

        if existing:
            host_id = existing[0]
            # Update existing host
            old_data = self.get_host_by_id(host_id)
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

            cursor.execute("""
                UPDATE hosts_v2
                SET ip_address = COALESCE(?, ip_address),
                    aliases = COALESCE(?, aliases),
                    environment = COALESCE(?, environment),
                    groups = COALESCE(?, groups),
                    role = COALESCE(?, role),
                    service = COALESCE(?, service),
                    ssh_port = COALESCE(?, ssh_port),
                    source_id = COALESCE(?, source_id),
                    metadata = COALESCE(?, metadata),
                    updated_at = ?
                WHERE id = ?
            """, (
                ip_address,
                json.dumps(aliases) if aliases else None,
                environment,
                json.dumps(groups) if groups else None,
                role,
                service,
                ssh_port,
                source_id,
                json.dumps(metadata) if metadata else None,
                now,
                host_id,
            ))

            # Record version if there were changes
            if changes:
                self._add_host_version(cursor, host_id, changes, changed_by)

        else:
            # Insert new host
            cursor.execute("""
                INSERT INTO hosts_v2
                (hostname, ip_address, aliases, environment, groups, role, service,
                 ssh_port, status, source_id, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?, ?, ?)
            """, (
                hostname.lower(),
                ip_address,
                json.dumps(aliases or []),
                environment,
                json.dumps(groups or []),
                role,
                service,
                ssh_port,
                source_id,
                json.dumps(metadata or {}),
                now,
                now,
            ))
            host_id = cursor.lastrowid

            # Record initial version
            self._add_host_version(cursor, host_id, {"action": "created"}, changed_by)

        conn.commit()
        conn.close()

        logger.debug(f"Added/updated host: {hostname}")
        return host_id

    def _add_host_version(
        self,
        cursor: sqlite3.Cursor,
        host_id: int,
        changes: Dict,
        changed_by: str,
    ):
        """Add a version entry for a host."""
        # Get current version number
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

    def _compute_changes(self, old_data: Dict, new_data: Dict) -> Dict:
        """Compute changes between old and new data."""
        changes = {}
        for key, new_value in new_data.items():
            if new_value is not None:
                old_value = old_data.get(key)
                if old_value != new_value:
                    changes[key] = {"old": old_value, "new": new_value}
        return changes

    def get_host_by_id(self, host_id: int) -> Optional[Dict]:
        """Get a host by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM hosts_v2 WHERE id = ?", (host_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._host_row_to_dict(row)
        return None

    def get_host_by_name(self, hostname: str) -> Optional[Dict]:
        """Get a host by hostname (case-insensitive)."""
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
        limit: int = 100,
    ) -> List[Dict]:
        """Search hosts with various filters."""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM hosts_v2 WHERE 1=1"
        params = []

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

        query += " ORDER BY hostname LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._host_row_to_dict(row) for row in rows]

    def get_all_hosts(self) -> List[Dict]:
        """Get all hosts."""
        return self.search_hosts(limit=10000)

    def update_host_status(self, host_id: int, status: str):
        """Update host status (online, offline, unknown)."""
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
        """Delete a host by hostname."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM hosts_v2 WHERE hostname = ?", (hostname.lower(),))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()

        if deleted:
            logger.info(f"Deleted host: {hostname}")
        return deleted

    def get_host_versions(self, host_id: int) -> List[Dict]:
        """Get version history for a host."""
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

    # ==================== Host Relations ====================

    def add_relation(
        self,
        source_hostname: str,
        target_hostname: str,
        relation_type: str,
        confidence: float = 1.0,
        validated: bool = False,
        metadata: Optional[Dict] = None,
    ) -> Optional[int]:
        """Add a relation between two hosts."""
        source_host = self.get_host_by_name(source_hostname)
        target_host = self.get_host_by_name(target_hostname)

        if not source_host or not target_host:
            logger.warning(f"Cannot add relation: host not found")
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

            logger.debug(f"Added relation: {source_hostname} --[{relation_type}]--> {target_hostname}")
            return relation_id

        except sqlite3.IntegrityError:
            conn.close()
            return None

    def get_relations(
        self,
        hostname: Optional[str] = None,
        relation_type: Optional[str] = None,
        validated_only: bool = False,
    ) -> List[Dict]:
        """Get host relations."""
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

        if hostname:
            host = self.get_host_by_name(hostname)
            if host:
                query += " AND (r.source_host_id = ? OR r.target_host_id = ?)"
                params.extend([host["id"], host["id"]])

        if relation_type:
            query += " AND r.relation_type = ?"
            params.append(relation_type)

        if validated_only:
            query += " AND r.validated_by_user = 1"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def validate_relation(self, relation_id: int):
        """Mark a relation as validated by user."""
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
        """Delete a relation."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM host_relations WHERE id = ?", (relation_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()
        return deleted

    # ==================== Scan Cache ====================

    def get_scan_cache(self, host_id: int, scan_type: str) -> Optional[Dict]:
        """Get cached scan data if not expired."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM scan_cache
            WHERE host_id = ? AND scan_type = ? AND expires_at > ?
        """, (host_id, scan_type, datetime.now().isoformat()))

        row = cursor.fetchone()
        conn.close()

        if row:
            result = self._row_to_dict(row)
            result["data"] = json.loads(result["data"])
            return result
        return None

    def save_scan_cache(
        self,
        host_id: int,
        scan_type: str,
        data: Dict,
        ttl_seconds: int,
    ):
        """Save scan data to cache."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        expires_at = now + timedelta(seconds=ttl_seconds)

        cursor.execute("""
            INSERT OR REPLACE INTO scan_cache
            (host_id, scan_type, data, ttl_seconds, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            host_id,
            scan_type,
            json.dumps(data),
            ttl_seconds,
            now.isoformat(),
            expires_at.isoformat(),
        ))

        conn.commit()
        conn.close()

    def delete_scan_cache(
        self,
        host_id: Optional[int] = None,
        scan_type: Optional[str] = None,
    ):
        """Delete scan cache entries."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if host_id and scan_type:
            cursor.execute(
                "DELETE FROM scan_cache WHERE host_id = ? AND scan_type = ?",
                (host_id, scan_type)
            )
        elif host_id:
            cursor.execute("DELETE FROM scan_cache WHERE host_id = ?", (host_id,))
        elif scan_type:
            cursor.execute("DELETE FROM scan_cache WHERE scan_type = ?", (scan_type,))
        else:
            cursor.execute("DELETE FROM scan_cache")

        conn.commit()
        conn.close()

    def cleanup_expired_cache(self):
        """Remove all expired cache entries."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM scan_cache WHERE expires_at < ?", (datetime.now().isoformat(),))
        deleted = cursor.rowcount

        conn.commit()
        conn.close()

        if deleted > 0:
            logger.debug(f"Cleaned up {deleted} expired cache entries")

    # ==================== Hostname-based Cache Helpers ====================

    def set_scan_cache(
        self,
        hostname: str,
        scan_type: str,
        data: Dict,
        ttl_seconds: int,
    ):
        """Save scan cache by hostname (convenience method).

        Only caches data for hosts that exist in the inventory.
        For hosts not in inventory, the cache is memory-only (in CacheManager).
        """
        host = self.get_host_by_name(hostname)
        if host:
            self.save_scan_cache(host["id"], scan_type, data, ttl_seconds)
        # If host not in inventory, skip persistent cache (use memory cache only)

    def get_scan_cache_by_hostname(
        self,
        hostname: str,
        scan_type: str,
    ) -> Optional[Dict]:
        """Get scan cache by hostname (convenience method)."""
        host = self.get_host_by_name(hostname)
        if host:
            return self.get_scan_cache(host["id"], scan_type)
        return None

    def clear_host_cache(self, hostname: str):
        """Clear all cached scan data for a hostname."""
        host = self.get_host_by_name(hostname)
        if host:
            self.delete_scan_cache(host_id=host["id"])

    # ==================== Local Context ====================

    def get_local_context(self) -> Optional[Dict]:
        """Get the full local context."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM local_context ORDER BY category, key")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        context = {}
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

    def save_local_context(self, context: Dict):
        """Save local context to database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

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
        conn.close()
        logger.info("Local context saved to database")

    def has_local_context(self) -> bool:
        """Check if local context exists."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM local_context")
        count = cursor.fetchone()[0]
        conn.close()

        return count > 0

    # ==================== Snapshots ====================

    def create_snapshot(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> int:
        """Create a snapshot of the current inventory."""
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

        logger.info(f"Created inventory snapshot: {name} ({len(hosts)} hosts)")
        return snapshot_id

    def list_snapshots(self, limit: int = 20) -> List[Dict]:
        """List inventory snapshots."""
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

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict]:
        """Get a snapshot by ID."""
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
        """Delete a snapshot."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM inventory_snapshots WHERE id = ?", (snapshot_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()
        return deleted

    # ==================== Utilities ====================

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert a database row to dictionary."""
        return dict(row)

    def _host_row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert a host row to dictionary with JSON parsing."""
        d = dict(row)
        # Parse JSON fields
        for field in ["aliases", "groups", "metadata"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
        return d

    def get_stats(self) -> Dict[str, Any]:
        """Get inventory statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()

        stats = {}

        # Total hosts
        cursor.execute("SELECT COUNT(*) FROM hosts_v2")
        stats["total_hosts"] = cursor.fetchone()[0]

        # By environment
        cursor.execute("""
            SELECT environment, COUNT(*) FROM hosts_v2
            GROUP BY environment
        """)
        stats["by_environment"] = {row[0] or "unknown": row[1] for row in cursor.fetchall()}

        # By source
        cursor.execute("""
            SELECT s.name, COUNT(h.id)
            FROM inventory_sources s
            LEFT JOIN hosts_v2 h ON h.source_id = s.id
            GROUP BY s.id
        """)
        stats["by_source"] = {row[0]: row[1] for row in cursor.fetchall()}

        # Relations
        cursor.execute("SELECT COUNT(*) FROM host_relations")
        stats["total_relations"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM host_relations WHERE validated_by_user = 1")
        stats["validated_relations"] = cursor.fetchone()[0]

        # Cache
        cursor.execute("SELECT COUNT(*) FROM scan_cache WHERE expires_at > ?", (datetime.now().isoformat(),))
        stats["cached_scans"] = cursor.fetchone()[0]

        conn.close()
        return stats

    @classmethod
    def reset_instance(cls):
        """Reset singleton instance (for testing)."""
        cls._instance = None


# Convenience function
def get_inventory_repository(db_path: Optional[str] = None) -> InventoryRepository:
    """Get the inventory repository singleton."""
    return InventoryRepository(db_path)
