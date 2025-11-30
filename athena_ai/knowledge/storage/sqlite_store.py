import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.knowledge.storage.models import AuditEntry, SessionRecord
from athena_ai.utils.logger import logger


class SQLiteStore:
    """Handles SQLite storage operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database and create tables."""
        with self._connection() as conn:
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
            logger.debug(f"SQLite initialized at {self.db_path}")

    @contextmanager
    def _connection(self):
        """Context manager for SQLite connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(self, session_id: str, env: str = "dev", metadata: Optional[Dict] = None) -> bool:
        """Create a new session record."""
        with self._connection() as conn:
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
        with self._connection() as conn:
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
        with self._connection() as conn:
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
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                return SessionRecord(**dict(row))
            return None

    def list_sessions(self, limit: int = 20) -> List[SessionRecord]:
        """List recent sessions."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sessions
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,))
            return [SessionRecord(**dict(row)) for row in cursor.fetchall()]

    # =========================================================================
    # Audit Logging
    # =========================================================================

    def log_audit(self, entry: AuditEntry) -> int:
        """Log an audit entry."""
        if not entry.timestamp:
            entry.timestamp = datetime.now().isoformat()

        with self._connection() as conn:
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

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [AuditEntry(**dict(row)) for row in cursor.fetchall()]

    # =========================================================================
    # Incident Storage
    # =========================================================================

    def store_incident(self, incident: Dict[str, Any], synced: int = 0):
        """Store an incident in SQLite."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO incidents
                (id, title, description, priority, status, created_at,
                 environment, service, host, symptoms, root_cause, solution, commands, tags, synced_to_graph)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                incident["id"],
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

    def get_incident(self, incident_id: str) -> Optional[Dict]:
        """Get an incident by ID."""
        with self._connection() as conn:
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

    def find_incidents(
        self,
        service: Optional[str] = None,
        environment: Optional[str] = None,
        status: str = 'resolved',
        limit: int = 5
    ) -> List[Dict]:
        """Find incidents in SQLite."""
        query = """
            SELECT * FROM incidents
            WHERE status = ?
        """
        params = [status]

        if service:
            query += " AND service = ?"
            params.append(service)

        if environment:
            query += " AND environment = ?"
            params.append(environment)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
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

    def mark_incident_synced(self, incident_id: str):
        """Mark an incident as synced to graph."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE incidents SET synced_to_graph = 1 WHERE id = ?",
                (incident_id,)
            )
            conn.commit()

    def get_unsynced_incidents(self) -> List[Dict]:
        """Get incidents not yet synced to graph."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE synced_to_graph = 0")
            incidents = []
            for row in cursor.fetchall():
                incident = dict(row)
                for field in ["symptoms", "commands", "tags"]:
                    if incident.get(field):
                        incident[field] = json.loads(incident[field])
                incidents.append(incident)
            return incidents

    # =========================================================================
    # Configuration
    # =========================================================================

    def set_config(self, key: str, value: Any) -> bool:
        """Set a configuration value."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO config (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.now().isoformat()))
            conn.commit()
            return True

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def get_stats(self) -> Dict[str, Any]:
        """Get SQLite stats."""
        stats = {"path": self.db_path, "available": True}
        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM sessions")
            stats["sessions"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM audit_log")
            stats["audit_entries"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM incidents")
            stats["incidents"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM incidents WHERE synced_to_graph = 0")
            stats["unsynced_incidents"] = cursor.fetchone()[0]
        return stats
