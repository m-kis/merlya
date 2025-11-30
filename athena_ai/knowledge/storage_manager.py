"""
Hybrid Storage Manager for Athena.

Combines:
- SQLite: Sessions, audit logs, configuration (fast, local, always available)
- FalkorDB: Knowledge graph, incidents, patterns (optional, rich queries)

If FalkorDB is not available, gracefully degrades to SQLite-only mode.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.knowledge.falkordb_client import FalkorDBConfig
from athena_ai.knowledge.storage.falkordb_store import FalkorDBStore
from athena_ai.knowledge.storage.models import AuditEntry, SessionRecord
from athena_ai.knowledge.storage.sqlite_store import SQLiteStore
from athena_ai.utils.logger import logger


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

        self.sqlite = SQLiteStore(sqlite_path)

        # FalkorDB setup
        self.falkordb = FalkorDBStore(falkordb_config, enable_falkordb)

    # =========================================================================
    # Connection Management
    # =========================================================================

    def connect_falkordb(self) -> bool:
        """Connect to FalkorDB."""
        return self.falkordb.connect()

    @property
    def falkordb_available(self) -> bool:
        """Check if FalkorDB is connected and available."""
        return self.falkordb.available

    # =========================================================================
    # Session Management (SQLite)
    # =========================================================================

    def create_session(self, session_id: str, env: str = "dev", metadata: Optional[Dict] = None) -> bool:
        """Create a new session record."""
        return self.sqlite.create_session(session_id, env, metadata)

    def end_session(self, session_id: str) -> bool:
        """Mark a session as ended."""
        return self.sqlite.end_session(session_id)

    def update_session_stats(
        self,
        session_id: str,
        queries: int = 0,
        commands: int = 0,
        incidents: int = 0
    ):
        """Update session statistics."""
        self.sqlite.update_session_stats(session_id, queries, commands, incidents)

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Get a session record."""
        return self.sqlite.get_session(session_id)

    def list_sessions(self, limit: int = 20) -> List[SessionRecord]:
        """List recent sessions."""
        return self.sqlite.list_sessions(limit)

    # =========================================================================
    # Audit Logging (SQLite)
    # =========================================================================

    def log_audit(self, entry: AuditEntry) -> int:
        """Log an audit entry."""
        return self.sqlite.log_audit(entry)

    def get_audit_log(
        self,
        session_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditEntry]:
        """Query audit log with filters."""
        return self.sqlite.get_audit_log(session_id, action, since, limit)

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

        # Try to store in FalkorDB
        synced = 0
        if self.falkordb.store_incident(incident):
            synced = 1

        # Always store in SQLite
        self.sqlite.store_incident(incident, synced)

        return incident_id

    def get_incident(self, incident_id: str) -> Optional[Dict]:
        """Get an incident by ID."""
        # Try FalkorDB first for richer data
        node = self.falkordb.get_node("Incident", {"id": incident_id})
        if node:
            return node

        # Fallback to SQLite
        return self.sqlite.get_incident(incident_id)

    def find_similar_incidents(
        self,
        symptoms: Optional[List[str]] = None,
        service: Optional[str] = None,
        environment: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict]:
        """
        Find similar past incidents.

        Uses FalkorDB for pattern matching if available,
        falls back to keyword search in SQLite.
        """
        # Try FalkorDB with graph queries
        if self.falkordb_available and symptoms:
            results = self.falkordb.find_similar_incidents(limit)
            if results:
                return results

        # Fallback to SQLite
        return self.sqlite.find_incidents(service, environment, limit=limit)

    # =========================================================================
    # Configuration (SQLite)
    # =========================================================================

    def set_config(self, key: str, value: Any) -> bool:
        """Set a configuration value."""
        return self.sqlite.set_config(key, value)

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.sqlite.get_config(key, default)

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
        unsynced_incidents = self.sqlite.get_unsynced_incidents()
        for incident in unsynced_incidents:
            if self.falkordb.store_incident(incident):
                self.sqlite.mark_incident_synced(incident["id"])
                synced["incidents"] += 1

        logger.info(f"Synced to FalkorDB: {synced}")
        return synced

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = {
            "sqlite": self.sqlite.get_stats(),
            "falkordb": self.falkordb.get_stats(),
        }
        return stats
