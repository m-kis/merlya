"""
Merlya Audit - Logger implementation.

Logs security-sensitive operations to SQLite for audit trail.
Supports OpenTelemetry/Logfire for observability when configured.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import TYPE_CHECKING, Any

from loguru import logger

from .formatters import sanitize_args
from .models import AuditEvent, AuditEventType, ObservabilityStatus
from .storage import (
    MAX_RECENT_LIMIT,
    ensure_table,
    store_event,
)
from .storage import (
    export_json as storage_export_json,
)
from .storage import (
    get_recent as storage_get_recent,
)

# Optional logfire integration (PydanticAI's observability)
try:
    import logfire as _logfire

    LOGFIRE_AVAILABLE = True
except ImportError:
    _logfire = None  # type: ignore[assignment]
    LOGFIRE_AVAILABLE = False

if TYPE_CHECKING:
    from datetime import datetime

    from merlya.persistence.database import Database


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
    _init_lock: threading.Lock = threading.Lock()

    # Maximum allowed limit for get_recent queries (prevent excessive memory usage)
    MAX_RECENT_LIMIT = MAX_RECENT_LIMIT

    def __init__(self, enabled: bool = True, logfire_enabled: bool | None = None) -> None:
        """
        Initialize the audit logger.

        Args:
            enabled: Whether audit logging is enabled.
            logfire_enabled: Whether to send events to Logfire/OpenTelemetry.
                           None = auto-detect from LOGFIRE_TOKEN env var.
        """
        self.enabled = enabled
        self._db: Database | None = None
        self._initialized = False

        # Logfire/OpenTelemetry integration
        self._logfire_enabled = False
        if logfire_enabled is None:
            # Auto-detect: enable if LOGFIRE_TOKEN is set
            logfire_enabled = bool(os.getenv("LOGFIRE_TOKEN"))

        if logfire_enabled and LOGFIRE_AVAILABLE and _logfire:
            try:
                # Configure logfire if not already configured
                if not _logfire.DEFAULT_LOGFIRE_INSTANCE._initialized:  # type: ignore[attr-defined]
                    _logfire.configure(
                        service_name="merlya",
                        send_to_logfire="if-token-present",
                    )
                self._logfire_enabled = True
                logger.debug("Logfire observability enabled for audit logging")
            except Exception as e:
                logger.warning(
                    f"⚠️ Logfire configuration failed: {e}. Audit logs will only be stored locally."
                )

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
        if self._db:
            await ensure_table(self._db)

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

        # Log to Logfire/OpenTelemetry (if enabled)
        if self._logfire_enabled and _logfire:
            try:
                # Create a span with structured attributes
                level = "info" if event.success else "warn"
                _logfire.log(  # type: ignore[call-arg]
                    level,  # type: ignore[arg-type]
                    f"audit.{event.event_type.value}",
                    event_id=event.event_id,
                    event_type=event.event_type.value,
                    action=event.action,
                    target=event.target,
                    user=event.user,
                    success=event.success,
                    **{  # type: ignore[arg-type]
                        f"details.{k}": v
                        for k, v in (event.details or {}).items()
                        if isinstance(v, (str, int, float, bool))
                    },  # Only primitive types
                )
            except Exception as e:
                logger.debug(f"Logfire logging failed: {e}")

        # Log to database (if available)
        if self._db and self._initialized:
            await store_event(self._db, event)

    # Specialized logging methods (delegate to log_methods module)
    async def log_command(
        self,
        command: str,
        host: str | None = None,
        output: str | None = None,
        exit_code: int | None = None,
        success: bool = True,
    ) -> None:
        """Log a command execution."""
        from .log_methods import log_command

        await log_command(self, command, host, output, exit_code, success)

    async def log_skill(
        self,
        skill_name: str,
        hosts: list[str],
        task: str | None = None,
        success: bool = True,
        duration_ms: int | None = None,
    ) -> None:
        """Log a skill invocation."""
        from .log_methods import log_skill

        await log_skill(self, skill_name, hosts, task, success, duration_ms)

    async def log_tool(
        self,
        tool_name: str,
        host: str | None = None,
        args: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        """Log a tool usage."""
        from .log_methods import log_tool

        await log_tool(self, tool_name, host, args, success)

    async def log_destructive(
        self,
        operation: str,
        target: str,
        confirmed: bool = False,
        success: bool | None = None,
    ) -> None:
        """Log a destructive operation."""
        from .log_methods import log_destructive

        await log_destructive(self, operation, target, confirmed, success)

    # Backward compatibility: expose sanitize methods as class methods
    _is_sensitive_key = staticmethod(
        lambda k: __import__(
            "merlya.audit.formatters", fromlist=["is_sensitive_key"]
        ).is_sensitive_key(k)
    )
    _is_sensitive_value = staticmethod(
        lambda v: __import__(
            "merlya.audit.formatters", fromlist=["is_sensitive_value"]
        ).is_sensitive_value(v)
    )
    _sanitize_value = staticmethod(
        lambda v: __import__("merlya.audit.formatters", fromlist=["sanitize_value"]).sanitize_value(
            v
        )
    )
    _sanitize_args = staticmethod(lambda a: sanitize_args(a))

    def get_observability_status(self) -> ObservabilityStatus:
        """Get the status of observability backends.

        Returns:
            ObservabilityStatus with logfire_enabled and sqlite_enabled booleans.
        """
        return ObservabilityStatus(
            logfire_enabled=self._logfire_enabled,
            sqlite_enabled=self._db is not None and self._initialized,
        )

    async def get_recent(
        self,
        limit: int = 50,
        event_type: AuditEventType | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent audit events.

        Args:
            limit: Maximum number of events to return (1-1000, default 50).
            event_type: Filter by event type.

        Returns:
            List of audit event dictionaries.

        Raises:
            ValueError: If limit is invalid (< 1 or > MAX_RECENT_LIMIT).
        """
        if not self._db:
            return []
        return await storage_get_recent(self._db, limit, event_type)

    async def export_json(
        self,
        limit: int = 100,
        event_type: AuditEventType | None = None,
        since: datetime | None = None,
    ) -> str:
        """
        Export audit logs as JSON (SIEM-compatible format).

        Args:
            limit: Maximum events to export (1-1000).
            event_type: Filter by event type.
            since: Only export events after this timestamp.

        Returns:
            JSON string with audit events in SIEM-friendly format.
        """
        import json

        if not self._db:
            return json.dumps({"events": [], "count": 0})
        return await storage_export_json(self._db, limit, event_type, since)

    @classmethod
    async def get_instance(cls, enabled: bool = True) -> AuditLogger:
        """Get singleton instance (thread-safe)."""
        if cls._lock is None:
            with cls._init_lock:
                if cls._lock is None:
                    cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(enabled=enabled)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset instance (for tests).

        Also resets the lock to None so it will be lazily recreated
        when get_instance is next called with an active event loop.
        """
        cls._instance = None
        cls._lock = None


async def get_audit_logger(enabled: bool = True) -> AuditLogger:
    """Get the audit logger singleton."""
    return await AuditLogger.get_instance(enabled=enabled)


__all__ = [
    "LOGFIRE_AVAILABLE",
    "AuditEvent",
    "AuditEventType",
    "AuditLogger",
    "ObservabilityStatus",
    "get_audit_logger",
]
