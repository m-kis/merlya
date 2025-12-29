"""
Merlya Persistence - Repositories.

Data access layer for database entities.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from merlya.config.constants import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from merlya.persistence.database import (
    Database,
    IntegrityError,
    from_json,
    to_json,
)
from merlya.persistence.models import Conversation, Host, OSInfo, Variable


class HostRepository:
    """Repository for Host entities."""

    def __init__(self, db: Database) -> None:
        """Initialize with database connection."""
        self.db = db

    async def create(self, host: Host) -> Host:
        """
        Create a new host.

        Raises:
            IntegrityError: If host name already exists.
            DatabaseError: On other database errors.
        """
        try:
            async with self.db.transaction():
                await self.db.execute(
                    """
                    INSERT INTO hosts (id, name, hostname, port, username, private_key,
                                      jump_host, elevation_method, tags, metadata, os_info,
                                      health_status, last_seen, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        host.id,
                        host.name,
                        host.hostname,
                        host.port,
                        host.username,
                        host.private_key,
                        host.jump_host,
                        host.elevation_method,
                        to_json(host.tags),
                        to_json(host.metadata),
                        to_json(host.os_info.model_dump() if host.os_info else None),
                        host.health_status,
                        host.last_seen,
                        host.created_at,
                        host.updated_at,
                    ),
                )
            logger.debug(f"🖥️ Host created: {host.name}")
            return host
        except IntegrityError as e:
            logger.error(f"❌ Host '{host.name}' already exists")
            raise ValueError(f"Host name '{host.name}' must be unique") from e

    async def get_by_id(self, host_id: str) -> Host | None:
        """Get host by ID."""
        async with await self.db.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)) as cursor:
            row = await cursor.fetchone()
            return self._row_to_host(row) if row else None

    async def get_by_name(self, name: str) -> Host | None:
        """Get host by name."""
        async with await self.db.execute(
            "SELECT * FROM hosts WHERE lower(name) = lower(?)",
            (name,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_host(row) if row else None

    async def get_by_hostname(self, hostname: str) -> Host | None:
        """Get host by hostname (IP or DNS name)."""
        async with await self.db.execute(
            "SELECT * FROM hosts WHERE lower(hostname) = lower(?)",
            (hostname,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_host(row) if row else None

    async def get_all(self) -> list[Host]:
        """Get all hosts."""
        async with await self.db.execute("SELECT * FROM hosts ORDER BY lower(name)") as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_host(row) for row in rows]

    async def get_by_tag(self, tag: str) -> list[Host]:
        """
        Get hosts with specific tag.

        Uses JSON functions to safely search in the tags array.
        """
        # Validate tag to prevent injection (only allow alphanumeric, dash, underscore)
        if not tag or not all(c.isalnum() or c in "-_" for c in tag):
            logger.warning(f"⚠️ Invalid tag format: {tag}")
            return []

        # Use JSON_EACH to safely search in the JSON array
        async with await self.db.execute(
            """
            SELECT DISTINCT h.* FROM hosts h
            WHERE EXISTS (
                SELECT 1 FROM json_each(h.tags) AS t
                WHERE t.value = ?
            )
            ORDER BY h.name
            """,
            (tag,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_host(row) for row in rows]

    async def update(self, host: Host) -> Host:
        """Update an existing host."""
        host.updated_at = datetime.now()
        async with self.db.transaction():
            await self.db.execute(
                """
                UPDATE hosts SET
                    hostname = ?, port = ?, username = ?, private_key = ?,
                    jump_host = ?, elevation_method = ?, tags = ?, metadata = ?,
                    os_info = ?, health_status = ?, last_seen = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    host.hostname,
                    host.port,
                    host.username,
                    host.private_key,
                    host.jump_host,
                    host.elevation_method,
                    to_json(host.tags),
                    to_json(host.metadata),
                    to_json(host.os_info.model_dump() if host.os_info else None),
                    host.health_status,
                    host.last_seen,
                    host.updated_at,
                    host.id,
                ),
            )
        logger.debug(f"🖥️ Host updated: {host.name}")
        return host

    async def update_metadata(self, host_id: str, metadata: dict[str, Any]) -> bool:
        """Update only the metadata field for a host.

        This is more efficient than full update when only metadata changes.

        Args:
            host_id: Host ID.
            metadata: New metadata dict.

        Returns:
            True if updated, False if host not found.
        """
        async with (
            self.db.transaction(),
            await self.db.execute(
                "UPDATE hosts SET metadata = ?, updated_at = ? WHERE id = ?",
                (to_json(metadata), datetime.now(), host_id),
            ) as cursor,
        ):
            updated = bool(cursor.rowcount and cursor.rowcount > 0)
            if updated:
                logger.debug(f"🖥️ Host metadata updated: {host_id}")
            return updated

    async def delete(self, host_id: str) -> bool:
        """Delete a host."""
        async with (
            self.db.transaction(),
            await self.db.execute("DELETE FROM hosts WHERE id = ?", (host_id,)) as cursor,
        ):
            deleted = bool(cursor.rowcount and cursor.rowcount > 0)
            if deleted:
                logger.debug(f"🖥️ Host deleted: {host_id}")
            return deleted

    async def count(self) -> int:
        """Count total hosts."""
        async with await self.db.execute("SELECT COUNT(*) FROM hosts") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def list(self) -> list[Host]:
        """Alias for get_all() for API compatibility."""
        return await self.get_all()

    def _row_to_host(self, row: Any) -> Host:
        """Convert database row to Host model."""
        from merlya.persistence.models import ElevationMethod

        os_info_data = from_json(row["os_info"])
        return Host(
            id=row["id"],
            name=row["name"],
            hostname=row["hostname"],
            port=row["port"],
            username=row["username"],
            private_key=row["private_key"],
            jump_host=row["jump_host"],
            # Handle NULL elevation_method (for hosts created before this field)
            elevation_method=row["elevation_method"]
            if row["elevation_method"]
            else ElevationMethod.NONE,
            tags=from_json(row["tags"]) or [],
            metadata=from_json(row["metadata"]) or {},
            os_info=OSInfo(**os_info_data) if os_info_data else None,
            health_status=row["health_status"],
            last_seen=row["last_seen"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class VariableRepository:
    """Repository for Variable entities."""

    def __init__(self, db: Database) -> None:
        """Initialize with database connection."""
        self.db = db

    async def set(self, name: str, value: str, is_env: bool = False) -> Variable:
        """Set a variable (insert or update)."""
        async with self.db.transaction():
            await self.db.execute(
                """
                INSERT INTO variables (name, value, is_env, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET value = ?, is_env = ?
                """,
                (name, value, is_env, datetime.now(), value, is_env),
            )
        # Don't log variable names (could be sensitive)
        logger.debug("📋 Variable set")
        return Variable(name=name, value=value, is_env=is_env)

    async def get(self, name: str) -> Variable | None:
        """Get a variable by name."""
        async with await self.db.execute(
            "SELECT * FROM variables WHERE name = ?", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Variable(
                    name=row["name"],
                    value=row["value"],
                    is_env=bool(row["is_env"]),
                    created_at=row["created_at"],
                )
            return None

    async def get_all(self) -> list[Variable]:
        """Get all variables."""
        async with await self.db.execute("SELECT * FROM variables ORDER BY name") as cursor:
            rows = await cursor.fetchall()
            return [
                Variable(
                    name=row["name"],
                    value=row["value"],
                    is_env=bool(row["is_env"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def delete(self, name: str) -> bool:
        """Delete a variable."""
        async with (
            self.db.transaction(),
            await self.db.execute("DELETE FROM variables WHERE name = ?", (name,)) as cursor,
        ):
            deleted = bool(cursor.rowcount and cursor.rowcount > 0)
            if deleted:
                logger.debug("📋 Variable deleted")
            return deleted


class ConversationRepository:
    """Repository for Conversation entities."""

    def __init__(self, db: Database) -> None:
        """Initialize with database connection."""
        self.db = db

    async def create(self, conv: Conversation) -> Conversation:
        """Create a new conversation."""
        async with self.db.transaction():
            await self.db.execute(
                """
                INSERT INTO conversations (id, title, messages, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conv.id,
                    conv.title,
                    to_json(conv.messages),
                    conv.summary,
                    conv.created_at,
                    conv.updated_at,
                ),
            )
        logger.debug(f"💬 Conversation created: {conv.id[:8]}...")
        return conv

    async def get_by_id(self, conv_id: str) -> Conversation | None:
        """Get conversation by ID."""
        async with await self.db.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_conversation(row) if row else None

    async def get_recent(self, limit: int = DEFAULT_LIST_LIMIT) -> list[Conversation]:
        """Get recent conversations."""
        # Validate limit
        limit = max(1, min(limit, MAX_LIST_LIMIT))
        async with await self.db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_conversation(row) for row in rows]

    async def update(self, conv: Conversation) -> Conversation:
        """Update a conversation."""
        conv.updated_at = datetime.now()
        async with self.db.transaction():
            await self.db.execute(
                """
                UPDATE conversations SET
                    title = ?, messages = ?, summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    conv.title,
                    to_json(conv.messages),
                    conv.summary,
                    conv.updated_at,
                    conv.id,
                ),
            )
        return conv

    async def delete(self, conv_id: str) -> bool:
        """Delete a conversation."""
        async with (
            self.db.transaction(),
            await self.db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,)) as cursor,
        ):
            return bool(cursor.rowcount and cursor.rowcount > 0)

    async def search(self, term: str, limit: int = DEFAULT_LIST_LIMIT) -> list[Conversation]:
        """
        Search conversations by content.

        Uses parameterized LIKE query (safe from SQL injection).
        """
        # Validate and sanitize
        if not term or len(term) > 200:
            return []

        limit = max(1, min(limit, MAX_LIST_LIMIT))

        # Escape LIKE special characters (backslash first, then % and _)
        escaped_term = term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        search_pattern = f"%{escaped_term}%"

        async with await self.db.execute(
            """
            SELECT * FROM conversations
            WHERE messages LIKE ? ESCAPE '\\'
               OR title LIKE ? ESCAPE '\\'
               OR summary LIKE ? ESCAPE '\\'
            ORDER BY updated_at DESC LIMIT ?
            """,
            (search_pattern, search_pattern, search_pattern, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_conversation(row) for row in rows]

    def _row_to_conversation(self, row: Any) -> Conversation:
        """Convert database row to Conversation model."""
        return Conversation(
            id=row["id"],
            title=row["title"],
            messages=from_json(row["messages"]) or [],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
