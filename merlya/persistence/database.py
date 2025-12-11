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
SCHEMA_VERSION = 1


class DatabaseError(Exception):
    """Base database error."""

    pass


class IntegrityError(DatabaseError):
    """Raised when a unique constraint is violated."""

    pass


class Database:
    """
    SQLite database connection manager.

    Provides async context manager for connections.
    Thread-safe singleton with asyncio.Lock.
    """

    _instance: Database | None = None
    _lock: asyncio.Lock | None = None

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
            """
        )
        await conn.commit()

        # Check schema version
        async with conn.execute("SELECT value FROM config WHERE key = 'schema_version'") as cursor:
            row = await cursor.fetchone()
            if not row:
                await conn.execute(
                    "INSERT INTO config (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                await conn.commit()

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
        if cls._lock is None:
            cls._lock = asyncio.Lock()

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
        cls._lock = None


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
