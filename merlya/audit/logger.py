"""
Merlya Audit - Logger implementation.

Logs security-sensitive operations to SQLite for audit trail.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.persistence.database import Database


class AuditEventType(str, Enum):
    """Types of audit events."""

    COMMAND_EXECUTED = "command_executed"
    SKILL_INVOKED = "skill_invoked"
    TOOL_USED = "tool_used"
    HOST_CONNECTED = "host_connected"
    CONFIG_CHANGED = "config_changed"
    SECRET_ACCESSED = "secret_accessed"
    DESTRUCTIVE_OPERATION = "destructive_operation"
    CONFIRMATION_REQUESTED = "confirmation_requested"
    CONFIRMATION_GRANTED = "confirmation_granted"
    CONFIRMATION_DENIED = "confirmation_denied"


@dataclass
class AuditEvent:
    """An audit event record.

    Attributes:
        event_type: Type of the event.
        action: Specific action taken.
        target: Target of the action (host, file, etc.).
        user: User who performed the action.
        details: Additional event details.
        success: Whether the action succeeded.
        timestamp: When the event occurred.
        event_id: Unique event identifier.
    """

    event_type: AuditEventType
    action: str
    target: str | None = None
    user: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "action": self.action,
            "target": self.target,
            "user": self.user,
            "details": self.details,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_log_line(self) -> str:
        """Format as a log line."""
        status = "OK" if self.success else "FAIL"
        target_str = f" on {self.target}" if self.target else ""
        return f"[{self.event_type.value}] {status}: {self.action}{target_str}"


class AuditLogger:
    """Audit logger for security-sensitive operations.

    Logs events to both loguru (console/file) and SQLite (persistent).

    Example:
        >>> audit = await get_audit_logger()
        >>> await audit.log_command("ssh_execute", "web-01", "uptime")
        >>> await audit.log_skill("disk_audit", ["web-01", "web-02"])
    """

    _instance: AuditLogger | None = None
    _lock: asyncio.Lock | None = None

    def __init__(self, enabled: bool = True) -> None:
        """
        Initialize the audit logger.

        Args:
            enabled: Whether audit logging is enabled.
        """
        self.enabled = enabled
        self._db: Database | None = None
        self._initialized = False

    async def initialize(self, db: Database | None = None) -> None:
        """
        Initialize the audit logger with database.

        Args:
            db: Database instance for persistent storage.
        """
        if self._initialized:
            return

        self._db = db

        if db:
            await self._ensure_table()

        self._initialized = True
        logger.debug("Audit logger initialized")

    async def _ensure_table(self) -> None:
        """Ensure audit_logs table exists."""
        if not self._db:
            return

        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                user TEXT,
                details TEXT,
                success INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_type ON audit_logs(event_type)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC)"
        )
        await self._db.commit()

    async def log(self, event: AuditEvent) -> None:
        """
        Log an audit event.

        Args:
            event: The audit event to log.
        """
        if not self.enabled:
            return

        # Log to loguru (always)
        log_func = logger.info if event.success else logger.warning
        log_func(f"AUDIT: {event.to_log_line()}")

        # Log to database (if available)
        if self._db and self._initialized:
            try:
                await self._db.execute(
                    """
                    INSERT INTO audit_logs (id, event_type, action, target, user, details, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type.value,
                        event.action,
                        event.target,
                        event.user,
                        json.dumps(event.details) if event.details else None,
                        1 if event.success else 0,
                    ),
                )
                await self._db.commit()
            except Exception as e:
                logger.warning(f"Failed to persist audit log: {e}")

    async def log_command(
        self,
        command: str,
        host: str | None = None,
        output: str | None = None,
        exit_code: int | None = None,
        success: bool = True,
    ) -> None:
        """Log a command execution."""
        details: dict[str, Any] = {}
        if output:
            # Truncate output for storage
            details["output_preview"] = output[:200] if len(output) > 200 else output
            details["output_length"] = len(output)
        if exit_code is not None:
            details["exit_code"] = exit_code

        await self.log(
            AuditEvent(
                event_type=AuditEventType.COMMAND_EXECUTED,
                action=command[:100],  # Truncate command
                target=host,
                details=details,
                success=success,
            )
        )

    async def log_skill(
        self,
        skill_name: str,
        hosts: list[str],
        task: str | None = None,
        success: bool = True,
        duration_ms: int | None = None,
    ) -> None:
        """Log a skill invocation."""
        details: dict[str, Any] = {
            "hosts": hosts,
            "host_count": len(hosts),
        }
        if task:
            details["task"] = task[:100]
        if duration_ms is not None:
            details["duration_ms"] = duration_ms

        await self.log(
            AuditEvent(
                event_type=AuditEventType.SKILL_INVOKED,
                action=skill_name,
                target=", ".join(hosts[:3]) + ("..." if len(hosts) > 3 else ""),
                details=details,
                success=success,
            )
        )

    async def log_tool(
        self,
        tool_name: str,
        host: str | None = None,
        args: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        """Log a tool usage."""
        details: dict[str, Any] = {}
        if args:
            # Sanitize args (remove sensitive data)
            safe_args = {
                k: v for k, v in args.items() if k not in ("password", "secret", "key", "token")
            }
            details["args"] = safe_args

        await self.log(
            AuditEvent(
                event_type=AuditEventType.TOOL_USED,
                action=tool_name,
                target=host,
                details=details,
                success=success,
            )
        )

    async def log_destructive(
        self,
        operation: str,
        target: str,
        confirmed: bool = False,
        success: bool | None = None,
    ) -> None:
        """Log a destructive operation."""
        if success is None:
            # Just requesting confirmation
            await self.log(
                AuditEvent(
                    event_type=AuditEventType.CONFIRMATION_REQUESTED,
                    action=operation,
                    target=target,
                )
            )
        elif confirmed:
            await self.log(
                AuditEvent(
                    event_type=AuditEventType.DESTRUCTIVE_OPERATION,
                    action=operation,
                    target=target,
                    success=success,
                    details={"confirmed": True},
                )
            )
        else:
            await self.log(
                AuditEvent(
                    event_type=AuditEventType.CONFIRMATION_DENIED,
                    action=operation,
                    target=target,
                    success=False,
                )
            )

    async def get_recent(
        self,
        limit: int = 50,
        event_type: AuditEventType | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent audit events.

        Args:
            limit: Maximum number of events to return.
            event_type: Filter by event type.

        Returns:
            List of audit event dictionaries.
        """
        if not self._db:
            return []

        query = "SELECT * FROM audit_logs"
        params: tuple[Any, ...] = ()

        if event_type:
            query += " WHERE event_type = ?"
            params = (event_type.value,)

        query += " ORDER BY created_at DESC LIMIT ?"
        params = (*params, limit)

        try:
            cursor = await self._db.execute(query, params)
            rows = await cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "action": row["action"],
                    "target": row["target"],
                    "user": row["user"],
                    "details": json.loads(row["details"]) if row["details"] else None,
                    "success": bool(row["success"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"Failed to get audit logs: {e}")
            return []

    @classmethod
    async def get_instance(cls, enabled: bool = True) -> AuditLogger:
        """Get singleton instance (thread-safe)."""
        if cls._lock is None:
            cls._lock = asyncio.Lock()

        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(enabled=enabled)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset instance (for tests)."""
        cls._instance = None
        cls._lock = None


async def get_audit_logger(enabled: bool = True) -> AuditLogger:
    """Get the audit logger singleton."""
    return await AuditLogger.get_instance(enabled=enabled)
