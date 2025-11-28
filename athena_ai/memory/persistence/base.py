"""
Base Repository - Common database connection and singleton pattern.

Provides thread-safe singleton pattern and SQLite connection management
for all repository mixins.
"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Dict, Generator, Optional, Set, Type

from athena_ai.utils.logger import logger

# Thread-safe singleton lock
_repository_lock = threading.Lock()

# Default SQLite connection timeout (seconds) to prevent indefinite blocking
_DEFAULT_TIMEOUT = 5.0


class BaseRepository:
    """
    Base repository handling database connection and singleton pattern.

    This class provides:
    - Thread-safe singleton instantiation (per-subclass)
    - SQLite connection management with Row factory
    - Foreign key constraint enforcement
    - Table initialization orchestration for mixins

    Note:
        The singleton pattern maintains separate instances per subclass.
        Each subclass gets its own singleton instance, allowing multiple
        repository types to coexist without sharing state.
    """

    # Class-level storage for per-subclass singletons
    _instances: ClassVar[Dict[Type["BaseRepository"], "BaseRepository"]] = {}
    _initialized_classes: ClassVar[Set[Type["BaseRepository"]]] = set()

    def __new__(cls, db_path: Optional[str] = None):
        """Thread-safe singleton pattern for repository (per-subclass).

        Args:
            db_path: Optional database path. Only used on first instantiation.

        Returns:
            The singleton instance for this specific class.
        """
        with _repository_lock:
            if cls not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[cls] = instance
            return cls._instances[cls]

    def __init__(self, db_path: Optional[str] = None):
        """Initialize repository with database path.

        Args:
            db_path: Optional database path. If not provided, uses
                ~/.athena/inventory.db as default.
        """
        cls = type(self)
        with _repository_lock:
            if cls in cls._initialized_classes:
                # Warn if trying to use different db_path after initialization
                if db_path and db_path != self.db_path:
                    logger.warning(
                        f"Repository already initialized with {self.db_path}, "
                        f"ignoring requested path {db_path}"
                    )
                return

            if db_path:
                # Ensure parent directory exists for custom paths
                db_path_obj = Path(db_path)
                db_path_obj.parent.mkdir(parents=True, exist_ok=True)
                self.db_path = str(db_path_obj)
            else:
                athena_dir = Path.home() / ".athena"
                athena_dir.mkdir(parents=True, exist_ok=True)
                self.db_path = str(athena_dir / "inventory.db")

            self._init_tables()
            cls._initialized_classes.add(cls)
            logger.debug(f"Repository initialized at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection.

        Returns:
            SQLite connection with Row factory and foreign keys enabled.

        Note:
            Uses a 5-second timeout to prevent indefinite blocking if the
            database is locked by another process or thread.
        """
        conn = sqlite3.connect(self.db_path, timeout=_DEFAULT_TIMEOUT)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self, *, commit: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections.

        Ensures connections are always closed, even if exceptions occur.
        Optionally commits on success or rolls back on failure.

        Args:
            commit: If True, commits on success and rolls back on exception.

        Yields:
            SQLite connection with Row factory and foreign keys enabled.
        """
        conn = self._get_connection()
        try:
            yield conn
            if commit:
                conn.commit()
        except Exception:
            if commit:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self) -> None:
        """Initialize all database tables.

        Orchestrates table creation by calling _init_*_tables methods
        from all mixins in the correct order (respecting foreign key
        dependencies).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            try:
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
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
        finally:
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
        """Reset singleton instance for this class (for testing).

        This allows tests to create fresh instances with different
        database paths. Only resets the instance for the specific class
        on which it's called, not all subclasses.
        """
        with _repository_lock:
            if cls in cls._instances:
                del cls._instances[cls]
            cls._initialized_classes.discard(cls)
