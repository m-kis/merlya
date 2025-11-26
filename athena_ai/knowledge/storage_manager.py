"""
Hybrid Storage Manager for Athena.

Combines:
- SQLite: Sessions, audit logs, configuration (fast, local, always available)
- FalkorDB: Knowledge graph, incidents, patterns (optional, rich queries)

If FalkorDB is not available, gracefully degrades to SQLite-only mode.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

from .falkordb_client import FalkorDBClient, FalkorDBConfig


@dataclass
class AuditEntry:
    """An audit log entry."""
    id: Optional[int] = None
    timestamp: str = ""
    action: str = ""
    target: str = ""
    command: str = ""
    user: str = ""
    result: str = ""  # success, failure, error
    details: str = ""
    session_id: str = ""
    priority: str = ""  # P0, P1, P2, P3


@dataclass
class SessionRecord:
    """A session record."""
    id: str = ""
    started_at: str = ""
    ended_at: Optional[str] = None
    env: str = ""
    queries: int = 0
    commands: int = 0
    incidents: int = 0
    metadata: str = "{}"


class StorageManager:
    """
    Hybrid storage manager combining SQLite and FalkorDB.

    SQLite is always used for:
    - Session tracking
    - Audit logs
    - Configuration
    - Fallback incident storage

    FalkorDB (when available) is used for:
    - Knowledge graph
    - Pattern matching
    - Incident correlation
    - CVE tracking
    """

    def __init__(
        self,
        sqlite_path: Optional[str] = None,
        falkordb_config: Optional[FalkorDBConfig] = None,
        enable_falkordb: bool = True,
    ):
        # SQLite setup
        if sqlite_path is None:
            sqlite_path = str(Path.home() / ".athena" / "storage.db")

        self.sqlite_path = sqlite_path
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_sqlite()

        # FalkorDB setup (optional)
        self.falkordb_enabled = enable_falkordb
        self._falkordb: Optional[FalkorDBClient] = None

        if enable_falkordb:
            self._falkordb = FalkorDBClient(falkordb_config)

    # =========================================================================
    # SQLite Connection Management
    # =========================================================================

    def _init_sqlite(self):
        """Initialize SQLite database and create tables."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()

            # Sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    env TEXT,
                    queries INTEGER DEFAULT 0,
                    commands INTEGER DEFAULT 0,
                    incidents INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}'
                )
            """)

            # Audit log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT,
                    command TEXT,
                    user TEXT,
                    result TEXT,
                    details TEXT,
                    session_id TEXT,
                    priority TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)

            # Incidents fallback table (when FalkorDB unavailable)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    priority TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    environment TEXT,
                    service TEXT,
                    host TEXT,
                    symptoms TEXT,  -- JSON array
                    root_cause TEXT,
                    solution TEXT,
                    commands TEXT,  -- JSON array
                    tags TEXT,  -- JSON array
                    synced_to_graph INTEGER DEFAULT 0
                )
            """)

            # Patterns fallback table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    symptoms TEXT,  -- JSON array
                    keywords TEXT,  -- JSON array
                    suggested_solution TEXT,
                    times_matched INTEGER DEFAULT 0,
                    last_matched TEXT,
                    synced_to_graph INTEGER DEFAULT 0
                )
            """)

            # Configuration table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_priority ON incidents(priority)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status)")

            conn.commit()
            logger.debug(f"SQLite initialized at {self.sqlite_path}")

    @contextmanager
    def _sqlite_connection(self):
        """Context manager for SQLite connections."""
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # =========================================================================
    # FalkorDB Connection
    # =========================================================================

    def connect_falkordb(self) -> bool:
        """
        Connect to FalkorDB.

        Returns:
            True if connected, False if unavailable
        """
        if not self.falkordb_enabled or self._falkordb is None:
            return False

        return self._falkordb.connect()

    @property
    def falkordb_available(self) -> bool:
        """Check if FalkorDB is connected and available."""
        return (
            self._falkordb is not None and
            self._falkordb.is_connected
        )

    def get_falkordb(self) -> Optional[FalkorDBClient]:
        """Get the FalkorDB client if available."""
        if self.falkordb_available:
            return self._falkordb
        return None

    # =========================================================================
    # Session Management (SQLite)
    # =========================================================================

    def create_session(self, session_id: str, env: str = "dev", metadata: Dict = None) -> bool:
        """Create a new session record."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sessions (id, started_at, env, metadata)
                VALUES (?, ?, ?, ?)
            """, (
                session_id,
                datetime.now().isoformat(),
                env,
                json.dumps(metadata or {}),
            ))
            conn.commit()
            return True

    def end_session(self, session_id: str) -> bool:
        """Mark a session as ended."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sessions SET ended_at = ? WHERE id = ?
            """, (datetime.now().isoformat(), session_id))
            conn.commit()
            return cursor.rowcount > 0

    def update_session_stats(
        self,
        session_id: str,
        queries: int = 0,
        commands: int = 0,
        incidents: int = 0
    ):
        """Update session statistics."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sessions
                SET queries = queries + ?,
                    commands = commands + ?,
                    incidents = incidents + ?
                WHERE id = ?
            """, (queries, commands, incidents, session_id))
            conn.commit()

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Get a session record."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                return SessionRecord(**dict(row))
            return None

    def list_sessions(self, limit: int = 20) -> List[SessionRecord]:
        """List recent sessions."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sessions
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,))
            return [SessionRecord(**dict(row)) for row in cursor.fetchall()]

    # =========================================================================
    # Audit Logging (SQLite)
    # =========================================================================

    def log_audit(self, entry: AuditEntry) -> int:
        """Log an audit entry."""
        if not entry.timestamp:
            entry.timestamp = datetime.now().isoformat()

        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log
                (timestamp, action, target, command, user, result, details, session_id, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.timestamp,
                entry.action,
                entry.target,
                entry.command,
                entry.user,
                entry.result,
                entry.details,
                entry.session_id,
                entry.priority,
            ))
            conn.commit()
            return cursor.lastrowid

    def get_audit_log(
        self,
        session_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditEntry]:
        """Query audit log with filters."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        if action:
            query += " AND action = ?"
            params.append(action)

        if since:
            query += " AND timestamp >= ?"
            params.append(since)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [AuditEntry(**dict(row)) for row in cursor.fetchall()]

    # =========================================================================
    # Incident Storage (Hybrid)
    # =========================================================================

    def store_incident(self, incident: Dict[str, Any]) -> str:
        """
        Store an incident.

        If FalkorDB is available, stores in graph.
        Always stores in SQLite as fallback/backup.
        """
        incident_id = incident.get("id") or f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        incident["id"] = incident_id

        # Always store in SQLite
        synced = 0
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO incidents
                (id, title, description, priority, status, created_at,
                 environment, service, host, symptoms, root_cause, solution, commands, tags, synced_to_graph)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                incident_id,
                incident.get("title", ""),
                incident.get("description", ""),
                incident.get("priority", "P3"),
                incident.get("status", "open"),
                incident.get("created_at") or datetime.now().isoformat(),
                incident.get("environment"),
                incident.get("service"),
                incident.get("host"),
                json.dumps(incident.get("symptoms", [])),
                incident.get("root_cause"),
                incident.get("solution"),
                json.dumps(incident.get("commands", [])),
                json.dumps(incident.get("tags", [])),
                synced,
            ))
            conn.commit()

        # Try to store in FalkorDB
        if self.falkordb_available:
            try:
                self._falkordb.create_node("Incident", {
                    "id": incident_id,
                    "title": incident.get("title", ""),
                    "description": incident.get("description", ""),
                    "priority": incident.get("priority", "P3"),
                    "status": incident.get("status", "open"),
                    "environment": incident.get("environment", ""),
                    "tags": incident.get("tags", []),
                })

                # Mark as synced
                with self._sqlite_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE incidents SET synced_to_graph = 1 WHERE id = ?",
                        (incident_id,)
                    )
                    conn.commit()

            except Exception as e:
                logger.warning(f"Failed to sync incident to FalkorDB: {e}")

        return incident_id

    def get_incident(self, incident_id: str) -> Optional[Dict]:
        """Get an incident by ID."""
        # Try FalkorDB first for richer data
        if self.falkordb_available:
            try:
                node = self._falkordb.find_node("Incident", {"id": incident_id})
                if node:
                    return node
            except Exception:
                pass

        # Fallback to SQLite
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
            row = cursor.fetchone()
            if row:
                incident = dict(row)
                # Parse JSON fields
                for field in ["symptoms", "commands", "tags"]:
                    if incident.get(field):
                        incident[field] = json.loads(incident[field])
                return incident
            return None

    def find_similar_incidents(
        self,
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Find similar past incidents.

        Uses FalkorDB for pattern matching if available,
        falls back to keyword search in SQLite.
        """
        # Try FalkorDB with graph queries
        if self.falkordb_available and symptoms:
            try:
                # Find incidents with similar symptoms
                # This is a simplified query - real implementation would use
                # embedding similarity or more sophisticated matching
                results = self._falkordb.query("""
                    MATCH (i:Incident)
                    WHERE i.status = 'resolved'
                    RETURN i
                    ORDER BY i.created_at DESC
                    LIMIT $limit
                """, {"limit": limit})

                return [r.get("i") for r in results if r.get("i")]

            except Exception as e:
                logger.debug(f"FalkorDB query failed, using SQLite: {e}")

        # Fallback to SQLite
        query = """
            SELECT * FROM incidents
            WHERE status = 'resolved'
        """
        params = []

        if service:
            query += " AND service = ?"
            params.append(service)

        if environment:
            query += " AND environment = ?"
            params.append(environment)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            incidents = []
            for row in cursor.fetchall():
                incident = dict(row)
                for field in ["symptoms", "commands", "tags"]:
                    if incident.get(field):
                        incident[field] = json.loads(incident[field])
                incidents.append(incident)
            return incidents

    # =========================================================================
    # Configuration (SQLite)
    # =========================================================================

    def set_config(self, key: str, value: Any) -> bool:
        """Set a configuration value."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO config (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.now().isoformat()))
            conn.commit()
            return True

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    # =========================================================================
    # Sync Operations
    # =========================================================================

    def sync_to_falkordb(self) -> Dict[str, int]:
        """
        Sync unsynced data from SQLite to FalkorDB.

        Returns:
            Dict with counts of synced items
        """
        if not self.falkordb_available:
            if not self.connect_falkordb():
                logger.warning("FalkorDB not available for sync")
                return {"incidents": 0, "patterns": 0}

        synced = {"incidents": 0, "patterns": 0}

        # Sync incidents
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE synced_to_graph = 0")

            for row in cursor.fetchall():
                incident = dict(row)
                try:
                    self._falkordb.create_node("Incident", {
                        "id": incident["id"],
                        "title": incident["title"],
                        "description": incident.get("description", ""),
                        "priority": incident["priority"],
                        "status": incident["status"],
                        "environment": incident.get("environment", ""),
                    })

                    cursor.execute(
                        "UPDATE incidents SET synced_to_graph = 1 WHERE id = ?",
                        (incident["id"],)
                    )
                    synced["incidents"] += 1

                except Exception as e:
                    logger.warning(f"Failed to sync incident {incident['id']}: {e}")

            conn.commit()

        logger.info(f"Synced to FalkorDB: {synced}")
        return synced

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = {
            "sqlite": {
                "path": self.sqlite_path,
                "available": True,
            },
            "falkordb": {
                "enabled": self.falkordb_enabled,
                "available": self.falkordb_available,
            },
        }

        # SQLite stats
        with self._sqlite_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM sessions")
            stats["sqlite"]["sessions"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM audit_log")
            stats["sqlite"]["audit_entries"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM incidents")
            stats["sqlite"]["incidents"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM incidents WHERE synced_to_graph = 0")
            stats["sqlite"]["unsynced_incidents"] = cursor.fetchone()[0]

        # FalkorDB stats
        if self.falkordb_available:
            stats["falkordb"].update(self._falkordb.get_stats())

        return stats
