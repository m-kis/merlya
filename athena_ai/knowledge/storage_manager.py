"""
Hybrid Storage Manager for Athena.

Combines:
- SQLite: Sessions, audit logs, configuration (fast, local, always available)
- FalkorDB: Knowledge graph, incidents, patterns (optional, rich queries)

If FalkorDB is not available, gracefully degrades to SQLite-only mode.
Includes automatic retry mechanism and background sync capabilities.
"""

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from athena_ai.knowledge.falkordb_client import FalkorDBConfig
from athena_ai.knowledge.storage.falkordb_store import FalkorDBStore
from athena_ai.knowledge.storage.models import AuditEntry, SessionRecord
from athena_ai.knowledge.storage.sqlite_store import SQLiteStore
from athena_ai.utils.logger import logger


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number (0-indexed)."""
        delay = self.initial_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)


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

    Features:
    - Automatic retry with exponential backoff for FalkorDB operations
    - Background sync thread for deferred synchronization
    - Graceful degradation to SQLite-only mode
    """

    def __init__(
        self,
        sqlite_path: Optional[str] = None,
        falkordb_config: Optional[FalkorDBConfig] = None,
        enable_falkordb: bool = True,
        retry_config: Optional[RetryConfig] = None,
        auto_sync_interval: Optional[int] = None,  # Seconds, None = disabled
    ):
        # SQLite setup
        if sqlite_path is None:
            sqlite_path = str(Path.home() / ".athena" / "storage.db")

        self.sqlite = SQLiteStore(sqlite_path)

        # FalkorDB setup
        self.falkordb = FalkorDBStore(falkordb_config, enable_falkordb)

        # Retry configuration
        self.retry_config = retry_config or RetryConfig()

        # Background sync thread
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_stop_event = threading.Event()
        self._sync_interval = auto_sync_interval
        self._sync_lock = threading.Lock()

        # Start background sync if configured
        if auto_sync_interval and auto_sync_interval > 0:
            self._start_background_sync()

    def __del__(self):
        """Clean up background thread on deletion."""
        self.stop_background_sync()

    def _start_background_sync(self):
        """Start the background sync thread."""
        if self._sync_thread is not None and self._sync_thread.is_alive():
            return

        self._sync_stop_event.clear()
        self._sync_thread = threading.Thread(
            target=self._background_sync_loop,
            daemon=True,
            name="athena-falkordb-sync"
        )
        self._sync_thread.start()
        logger.debug(f"Started background sync thread (interval: {self._sync_interval}s)")

    def stop_background_sync(self):
        """Stop the background sync thread."""
        if self._sync_thread is None:
            return

        self._sync_stop_event.set()
        self._sync_thread.join(timeout=5.0)
        self._sync_thread = None
        logger.debug("Stopped background sync thread")

    def _background_sync_loop(self):
        """Background thread that periodically syncs to FalkorDB."""
        while not self._sync_stop_event.is_set():
            try:
                # Wait for interval or stop event
                if self._sync_stop_event.wait(timeout=self._sync_interval):
                    break  # Stop event was set

                # Perform sync with retry
                with self._sync_lock:
                    self._sync_with_retry()

            except Exception as e:
                logger.warning(f"Background sync error: {e}")
                # Continue loop even on error

    def _sync_with_retry(self) -> Dict[str, int]:
        """Sync to FalkorDB with retry logic."""
        return self._with_retry(
            self._do_sync,
            operation_name="sync_to_falkordb",
            default_result={"incidents": 0, "patterns": 0, "error": True}
        )

    def _do_sync(self) -> Dict[str, int]:
        """Actual sync implementation."""
        if not self.falkordb_available:
            if not self.connect_falkordb():
                raise ConnectionError("FalkorDB not available")

        synced = {"incidents": 0, "patterns": 0}

        # Sync incidents
        unsynced_incidents = self.sqlite.get_unsynced_incidents()
        for incident in unsynced_incidents:
            if self.falkordb.store_incident(incident):
                self.sqlite.mark_incident_synced(incident["id"])
                synced["incidents"] += 1

        return synced

    def _with_retry(
        self,
        operation: Callable,
        operation_name: str = "operation",
        default_result: Any = None,
    ) -> Any:
        """Execute an operation with retry logic.

        Args:
            operation: Callable to execute.
            operation_name: Name for logging.
            default_result: Result to return if all retries fail.

        Returns:
            Operation result or default_result on failure.
        """
        last_error = None

        for attempt in range(self.retry_config.max_retries):
            try:
                return operation()
            except Exception as e:
                last_error = e
                delay = self.retry_config.get_delay(attempt)
                logger.debug(
                    f"{operation_name} failed (attempt {attempt + 1}/{self.retry_config.max_retries}): {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)

        logger.warning(
            f"{operation_name} failed after {self.retry_config.max_retries} attempts: {last_error}"
        )
        return default_result

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

    def sync_to_falkordb(self, with_retry: bool = True) -> Dict[str, int]:
        """
        Sync unsynced data from SQLite to FalkorDB.

        Args:
            with_retry: Use retry logic if True (default).

        Returns:
            Dict with counts of synced items.
        """
        if with_retry:
            result = self._sync_with_retry()
        else:
            try:
                result = self._do_sync()
            except Exception as e:
                logger.warning(f"FalkorDB sync failed: {e}")
                result = {"incidents": 0, "patterns": 0, "error": True}

        if not result.get("error"):
            logger.info(f"Synced to FalkorDB: {result}")
        return result

    def trigger_sync(self) -> Dict[str, int]:
        """Trigger an immediate sync (thread-safe).

        Returns:
            Dict with counts of synced items.
        """
        with self._sync_lock:
            return self._sync_with_retry()

    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status.

        Returns:
            Dict with sync thread status and unsynced counts.
        """
        unsynced = self.sqlite.get_unsynced_incidents()
        return {
            "background_sync_enabled": self._sync_interval is not None,
            "sync_interval_seconds": self._sync_interval,
            "sync_thread_alive": self._sync_thread is not None and self._sync_thread.is_alive(),
            "unsynced_incidents": len(unsynced),
            "falkordb_available": self.falkordb_available,
        }

    def enable_background_sync(self, interval_seconds: int = 300):
        """Enable or update background sync interval.

        Args:
            interval_seconds: Sync interval in seconds.
        """
        self._sync_interval = interval_seconds
        self._start_background_sync()

    def disable_background_sync(self):
        """Disable background sync."""
        self.stop_background_sync()
        self._sync_interval = None

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
