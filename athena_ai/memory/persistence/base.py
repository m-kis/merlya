"""
Base Repository - Common database connection and singleton pattern.

Provides thread-safe singleton pattern and SQLite connection management
for all repository mixins.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from athena_ai.utils.logger import logger

# Thread-safe singleton lock
_repository_lock = threading.Lock()


class BaseRepository:
    """
    Base repository handling database connection and singleton pattern.

    This class provides:
    - Thread-safe singleton instantiation
    - SQLite connection management with Row factory
    - Foreign key constraint enforcement
    - Table initialization orchestration for mixins
    """

    _instance: Optional["BaseRepository"] = None
    _initialized: bool = False

    def __new__(cls, db_path: Optional[str] = None):
        """Thread-safe singleton pattern for repository.

        Args:
            db_path: Optional database path. Only used on first instantiation.

        Returns:
            The singleton instance.
        """
        if cls._instance is None:
            with _repository_lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        """Initialize repository with database path.

        Args:
            db_path: Optional database path. If not provided, uses
                ~/.athena/inventory.db as default.
        """
        with _repository_lock:
            if self._initialized:
                # Warn if trying to use different db_path after initialization
                if db_path and db_path != self.db_path:
                    logger.warning(
                        f"Repository already initialized with {self.db_path}, "
                        f"ignoring requested path {db_path}"
                    )
                return

            if db_path:
                self.db_path = db_path
            else:
                athena_dir = Path.home() / ".athena"
                athena_dir.mkdir(parents=True, exist_ok=True)
                self.db_path = str(athena_dir / "inventory.db")

            self._init_tables()
            self._initialized = True
            logger.debug(f"Repository initialized at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection.

        Returns:
            SQLite connection with Row factory and foreign keys enabled.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_tables(self) -> None:
        """Initialize all database tables.

        Orchestrates table creation by calling _init_*_tables methods
        from all mixins in the correct order (respecting foreign key
        dependencies).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Call mixin table initializers in dependency order
        # Sources must come before hosts (hosts reference sources)
        if hasattr(self, "_init_source_tables"):
            self._init_source_tables(cursor)

        # Hosts must come before relations, scan_cache (they reference hosts)
        if hasattr(self, "_init_host_tables"):
            self._init_host_tables(cursor)

        # Relations depend on hosts
        if hasattr(self, "_init_relation_tables"):
            self._init_relation_tables(cursor)

        # Scan cache depends on hosts
        if hasattr(self, "_init_scan_cache_tables"):
            self._init_scan_cache_tables(cursor)

        # Local context is independent
        if hasattr(self, "_init_local_context_tables"):
            self._init_local_context_tables(cursor)

        # Snapshots are independent
        if hasattr(self, "_init_snapshot_tables"):
            self._init_snapshot_tables(cursor)

        conn.commit()
        conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a database row to dictionary.

        Args:
            row: SQLite Row object.

        Returns:
            Dictionary with column names as keys.
        """
        return dict(row)

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing).

        This allows tests to create fresh instances with different
        database paths.
        """
        with _repository_lock:
            cls._instance = None
            cls._initialized = False
