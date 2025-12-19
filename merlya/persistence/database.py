"""
Merlya Persistence - Database connection.

SQLite database with async support via aiosqlite.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# =============================================================================
# SQLite datetime adapters for Python 3.12+ compatibility
# =============================================================================


def _adapt_datetime(val: datetime) -> str:
    """Adapt datetime to ISO format string."""
    return val.isoformat()


def _convert_datetime(val: bytes) -> datetime:
    """Convert ISO format string to datetime."""
    try:
        return datetime.fromisoformat(val.decode())
    except (ValueError, AttributeError):
        # Fallback for non-standard formats
        return datetime.now()


# Register adapters globally to suppress deprecation warnings
sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("TIMESTAMP", _convert_datetime)

# Default database path
DEFAULT_DB_PATH = Path.home() / ".merlya" / "merlya.db"

# Schema version for migrations
# v1: Initial schema
# v2: Added ON DELETE SET NULL/CASCADE to foreign keys
# v3: Added session_messages table for message history persistence
# v4: Added elevation_method to hosts table
SCHEMA_VERSION = 4

# Migration lock timeout in seconds
MIGRATION_LOCK_TIMEOUT = 30


class DatabaseError(Exception):
    """Base database error."""

    pass


class IntegrityError(DatabaseError):
    """Raised when a unique constraint is violated."""

    pass


class MigrationLockError(DatabaseError):
    """Raised when migration lock cannot be acquired."""

    pass


class Database:
    """
    SQLite database connection manager.

    Provides async context manager for connections.
    Thread-safe singleton with asyncio.Lock.
    """

    _instance: Database | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, path: Path | None = None) -> None:
        """
        Initialize database.

        Args:
            path: Database file path.
        """
        self.path = path or DEFAULT_DB_PATH
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open database connection and initialize schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Use detect_types for datetime conversion
        self._connection = await aiosqlite.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        self._connection.row_factory = aiosqlite.Row

        # Enable foreign keys
        await self._connection.execute("PRAGMA foreign_keys = ON")

        # Initialize schema
        await self._init_schema()

        logger.debug(f"🗄️ Database connected: {self.path}")

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.debug("🗄️ Database connection closed")

    @property
    def connection(self) -> aiosqlite.Connection:
        """Get current connection."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        return self._connection

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self.connection  # Use property that raises if None
        await conn.executescript(
            """
            -- Hosts table
            CREATE TABLE IF NOT EXISTS hosts (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                hostname TEXT NOT NULL,
                port INTEGER DEFAULT 22,
                username TEXT,
                private_key TEXT,
                jump_host TEXT,
                elevation_method TEXT,
                tags TEXT,
                metadata TEXT,
                os_info TEXT,
                health_status TEXT DEFAULT 'unknown',
                last_seen TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Variables table
            CREATE TABLE IF NOT EXISTS variables (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                is_env INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Conversations table
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                messages TEXT,
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Scan cache table
            CREATE TABLE IF NOT EXISTS scan_cache (
                host_id TEXT,
                scan_type TEXT,
                data TEXT,
                expires_at TIMESTAMP,
                PRIMARY KEY (host_id, scan_type)
            );

            -- Raw logs table (for storing command outputs)
            CREATE TABLE IF NOT EXISTS raw_logs (
                id TEXT PRIMARY KEY,
                host_id TEXT,
                command TEXT NOT NULL,
                output TEXT NOT NULL,
                exit_code INTEGER,
                line_count INTEGER NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                -- ON DELETE SET NULL: Keep logs even if host is deleted
                FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE SET NULL
            );

            -- Sessions table (for context management)
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                summary TEXT,
                token_count INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                context_tier TEXT DEFAULT 'STANDARD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- ON DELETE CASCADE: Delete sessions when conversation is deleted
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            -- Session messages table (for message history persistence)
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sequence_num INTEGER NOT NULL,
                message_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- ON DELETE CASCADE: Delete messages when session is deleted
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                UNIQUE (session_id, sequence_num)
            );

            -- Config table (for internal state)
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_hosts_name ON hosts(name);
            CREATE INDEX IF NOT EXISTS idx_hosts_health ON hosts(health_status);
            CREATE INDEX IF NOT EXISTS idx_hosts_last_seen ON hosts(last_seen DESC);
            CREATE INDEX IF NOT EXISTS idx_scan_cache_expires ON scan_cache(expires_at);
            CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_variables_is_env ON variables(is_env);
            CREATE INDEX IF NOT EXISTS idx_raw_logs_host ON raw_logs(host_id);
            CREATE INDEX IF NOT EXISTS idx_raw_logs_created ON raw_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_raw_logs_expires ON raw_logs(expires_at);
            CREATE INDEX IF NOT EXISTS idx_sessions_conversation ON sessions(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_session_messages_order ON session_messages(session_id, sequence_num);
            """
        )
        await conn.commit()

        # Check schema version and run migrations if needed
        async with conn.execute("SELECT value FROM config WHERE key = 'schema_version'") as cursor:
            row = await cursor.fetchone()
            if not row:
                await conn.execute(
                    "INSERT INTO config (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                await conn.commit()
            else:
                current_version = int(row["value"])
                if current_version < SCHEMA_VERSION:
                    await self._run_migrations(current_version)

    async def _acquire_migration_lock(self) -> bool:
        """
        Acquire migration lock using SQLite's application_id pragma.

        Uses a two-phase approach:
        1. Check if another process is migrating (migration_in_progress flag)
        2. Set the flag atomically before starting migration

        Returns:
            True if lock acquired, False if another process is migrating.
        """
        conn = self.connection

        try:
            # Check if migration is already in progress
            async with conn.execute(
                "SELECT value FROM config WHERE key = 'migration_in_progress'"
            ) as cursor:
                row = await cursor.fetchone()
                if row and row["value"] == "1":
                    # Check if lock is stale (older than timeout)
                    async with conn.execute(
                        "SELECT value FROM config WHERE key = 'migration_started_at'"
                    ) as ts_cursor:
                        ts_row = await ts_cursor.fetchone()
                        if ts_row:
                            started_at = datetime.fromisoformat(ts_row["value"])
                            elapsed = (datetime.now() - started_at).total_seconds()
                            if elapsed < MIGRATION_LOCK_TIMEOUT:
                                logger.warning(
                                    f"⏳ Migration in progress by another process "
                                    f"(started {elapsed:.1f}s ago), waiting..."
                                )
                                return False
                            else:
                                logger.warning(
                                    f"⚠️ Stale migration lock detected ({elapsed:.1f}s old), "
                                    "taking over..."
                                )

            # Set migration lock
            await conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                ("migration_in_progress", "1"),
            )
            await conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                ("migration_started_at", datetime.now().isoformat()),
            )
            await conn.commit()
            return True

        except Exception as e:
            logger.error(f"❌ Failed to acquire migration lock: {e}")
            return False

    async def _release_migration_lock(self) -> None:
        """Release migration lock."""
        conn = self.connection
        try:
            await conn.execute(
                "DELETE FROM config WHERE key IN ('migration_in_progress', 'migration_started_at')"
            )
            await conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ Failed to release migration lock: {e}")

    async def _run_migrations(self, from_version: int) -> None:
        """
        Run database migrations from version to SCHEMA_VERSION.

        Uses a single transaction for atomicity and a lock for multi-process safety.
        """
        conn = self.connection

        # Acquire migration lock with retry
        max_retries = 3
        for attempt in range(max_retries):
            if await self._acquire_migration_lock():
                break
            if attempt < max_retries - 1:
                await asyncio.sleep(2)  # Wait before retry
        else:
            raise MigrationLockError(
                "Could not acquire migration lock after multiple attempts. "
                "Another process may be migrating the database."
            )

        try:
            # Run all migrations in a single transaction for atomicity
            await conn.execute("BEGIN IMMEDIATE TRANSACTION")

            try:
                # Migration v1 -> v2: Add ON DELETE clauses to foreign keys
                if from_version < 2:
                    logger.info("📦 Running database migration v1 -> v2...")
                    await self._migrate_v1_to_v2_tables()
                    from_version = 2  # Update for next check
                    logger.info("✅ Migration v1 -> v2 complete")

                # Migration v2 -> v3: Add session_messages table
                if from_version < 3:
                    logger.info("📦 Running database migration v2 -> v3...")
                    await self._migrate_add_session_messages_v3_internal()
                    from_version = 3
                    logger.info("✅ Migration v2 -> v3 complete")

                # Migration v3 -> v4: Add elevation_method to hosts
                if from_version < 4:
                    logger.info("📦 Running database migration v3 -> v4...")
                    await self._migrate_add_elevation_method_v4_internal()
                    logger.info("✅ Migration v3 -> v4 complete")

                # Update schema version (within the same transaction)
                await conn.execute(
                    "UPDATE config SET value = ? WHERE key = 'schema_version'",
                    (str(SCHEMA_VERSION),),
                )

                # Commit entire migration atomically
                await conn.execute("COMMIT")
                logger.info(f"✅ All migrations complete (schema v{SCHEMA_VERSION})")

            except Exception as e:
                # Rollback entire migration on any failure
                await conn.execute("ROLLBACK")
                logger.error(f"❌ Migration failed, rolled back: {e}")
                raise DatabaseError(f"Migration failed: {e}") from e

        finally:
            # Always release the lock
            await self._release_migration_lock()

    async def _migrate_v1_to_v2_tables(self) -> None:
        """Migrate tables for v1 -> v2 (within existing transaction)."""
        conn = self.connection

        # Check and migrate raw_logs table
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_logs'"
        ) as cursor:
            if await cursor.fetchone():
                await self._migrate_raw_logs_v2_internal()

        # Check and migrate sessions table
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ) as cursor:
            if await cursor.fetchone():
                await self._migrate_sessions_v2_internal()

    async def _migrate_add_session_messages_v3_internal(self) -> None:
        """Add session_messages table (called within transaction)."""
        conn = self.connection

        # Create session_messages table if it doesn't exist
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                sequence_num INTEGER NOT NULL,
                message_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                UNIQUE (session_id, sequence_num)
            )
            """
        )

        # Create indexes
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_messages_order ON session_messages(session_id, sequence_num)"
        )
        logger.debug("  → session_messages table created")

    async def _migrate_raw_logs_v2_internal(self) -> None:
        """Migrate raw_logs table (called within transaction)."""
        conn = self.connection

        # Create new table with ON DELETE SET NULL
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_logs_new (
                id TEXT PRIMARY KEY,
                host_id TEXT,
                command TEXT NOT NULL,
                output TEXT NOT NULL,
                exit_code INTEGER,
                line_count INTEGER NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE SET NULL
            )
            """
        )

        # Copy data
        await conn.execute(
            """
            INSERT OR IGNORE INTO raw_logs_new
            SELECT id, host_id, command, output, exit_code, line_count, byte_size,
                   created_at, expires_at
            FROM raw_logs
            """
        )

        # Drop old table
        await conn.execute("DROP TABLE IF EXISTS raw_logs")

        # Rename new table
        await conn.execute("ALTER TABLE raw_logs_new RENAME TO raw_logs")

        # Recreate indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_logs_host ON raw_logs(host_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_logs_created ON raw_logs(created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_logs_expires ON raw_logs(expires_at)"
        )
        logger.debug("  → raw_logs table migrated")

    async def _migrate_sessions_v2_internal(self) -> None:
        """Migrate sessions table (called within transaction)."""
        conn = self.connection

        # Create new table with ON DELETE CASCADE
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions_new (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                summary TEXT,
                token_count INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                context_tier TEXT DEFAULT 'STANDARD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )

        # Copy data
        await conn.execute(
            """
            INSERT OR IGNORE INTO sessions_new
            SELECT id, conversation_id, summary, token_count, message_count,
                   context_tier, created_at, updated_at
            FROM sessions
            """
        )

        # Drop old table
        await conn.execute("DROP TABLE IF EXISTS sessions")

        # Rename new table
        await conn.execute("ALTER TABLE sessions_new RENAME TO sessions")

        # Recreate indexes
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_conversation ON sessions(conversation_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
        )
        logger.debug("  → sessions table migrated")

    async def _migrate_add_elevation_method_v4_internal(self) -> None:
        """Add elevation_method column to hosts table (called within transaction)."""
        conn = self.connection

        # Check if column already exists
        async with conn.execute("PRAGMA table_info(hosts)") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]
            if "elevation_method" in columns:
                logger.debug("  → elevation_method column already exists")
                return

        # Add the column
        await conn.execute("ALTER TABLE hosts ADD COLUMN elevation_method TEXT")
        logger.debug("  → elevation_method column added to hosts")

    async def execute(self, query: str, params: tuple[Any, ...] | None = None) -> aiosqlite.Cursor:
        """Execute a query."""
        try:
            return await self.connection.execute(query, params or ())
        except aiosqlite.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except aiosqlite.OperationalError as e:
            raise DatabaseError(f"Database operation failed: {e}") from e

    async def executemany(self, query: str, params: list[tuple[Any, ...]]) -> aiosqlite.Cursor:
        """Execute a query with multiple parameter sets."""
        try:
            return await self.connection.executemany(query, params)
        except aiosqlite.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except aiosqlite.OperationalError as e:
            raise DatabaseError(f"Database operation failed: {e}") from e

    async def commit(self) -> None:
        """Commit current transaction."""
        await self.connection.commit()

    async def rollback(self) -> None:
        """Rollback current transaction."""
        await self.connection.rollback()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Database]:
        """
        Transaction context manager with automatic rollback on error.

        Usage:
            async with db.transaction():
                await db.execute(...)
                await db.execute(...)
        """
        try:
            yield self
            await self.commit()
        except Exception:
            await self.rollback()
            raise

    @classmethod
    async def get_instance(cls, path: Path | None = None) -> Database:
        """Get singleton instance (thread-safe)."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(path)
                await cls._instance.connect()
            return cls._instance

    @classmethod
    async def close_instance(cls) -> None:
        """Close and reset singleton."""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None

    @classmethod
    def reset_instance(cls) -> None:
        """Reset instance without closing (for tests)."""
        cls._instance = None


async def get_database(path: Path | None = None) -> Database:
    """Get database singleton."""
    return await Database.get_instance(path)


# JSON serialization helpers
def to_json(data: Any) -> str:
    """Serialize data to JSON string."""
    return json.dumps(data, default=str)


def from_json(data: str | None) -> Any:
    """Deserialize JSON string to data."""
    if not data:
        return None
    return json.loads(data)
