"""
Merlya Audit - Logger implementation.

Logs security-sensitive operations to SQLite for audit trail.
Supports OpenTelemetry/Logfire for observability when configured.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple

from loguru import logger

# Optional logfire integration (PydanticAI's observability)
try:
    import logfire as _logfire

    LOGFIRE_AVAILABLE = True
except ImportError:
    _logfire = None  # type: ignore[assignment]
    LOGFIRE_AVAILABLE = False

if TYPE_CHECKING:
    from merlya.persistence.database import Database


class ObservabilityStatus(NamedTuple):
    """Status of observability backends.

    Attributes:
        logfire_enabled: Whether Logfire/OpenTelemetry is enabled.
        sqlite_enabled: Whether SQLite persistence is enabled.
    """

    logfire_enabled: bool
    sqlite_enabled: bool


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

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
        """Format as a log line.

        Uses truncated event_id (first 8 chars) for display while
        the full UUID is stored internally for global uniqueness.
        """
        status = "OK" if self.success else "FAIL"
        target_str = f" on {self.target}" if self.target else ""
        short_id = self.event_id[:8]
        return f"[{short_id}] [{self.event_type.value}] {status}: {self.action}{target_str}"


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
                logger.debug(f"Logfire not configured: {e}")

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

    # Patterns for detecting sensitive keys (case-insensitive substring match)
    _SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
        # Passwords
        "password",
        "passwd",
        "pwd",
        # Secrets and keys
        "secret",
        "key",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "accesskey",
        "private_key",
        "privatekey",
        # Authentication
        "auth",
        "credential",
        "bearer",
        "jwt",
        "oauth",
        # Session and identity
        "session",
        "cookie",
        "csrf",
        "nonce",
        # Certificates
        "cert",
        "certificate",
        "pem",
        # Connection strings and DSNs
        "connection_string",
        "connectionstring",
        "dsn",
        "database_url",
        "db_url",
        # Cloud provider specific
        "aws_secret",
        "azure_key",
        "gcp_key",
        # SSH
        "ssh_key",
        "id_rsa",
        "id_ed25519",
        # Encryption
        "encrypt",
        "decrypt",
        "salt",
        "iv",
        "hmac",
    )

    # Regex patterns for detecting sensitive values (regardless of key name)
    _SENSITIVE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
        # AWS access key IDs (start with AKIA, ABIA, ACCA, ASIA)
        re.compile(r"^A[KBS]IA[A-Z0-9]{16}$"),
        # AWS secret access keys (40 char base64-ish)
        re.compile(r"^[A-Za-z0-9/+=]{40}$"),
        # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
        re.compile(r"^gh[pousr]_[A-Za-z0-9_]{36,}$"),
        # Generic API keys (long alphanumeric strings, 32+ chars)
        re.compile(r"^[A-Za-z0-9_-]{32,}$"),
        # JWT tokens (three base64 parts separated by dots)
        re.compile(r"^eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*$"),
        # Bearer tokens
        re.compile(r"^Bearer\s+.{20,}$", re.IGNORECASE),
        # Basic auth (base64 encoded user:pass)
        re.compile(r"^Basic\s+[A-Za-z0-9+/=]{10,}$", re.IGNORECASE),
        # Private keys (PEM format indicators)
        re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
        # Hex-encoded secrets (32+ hex chars, likely hashes or keys)
        re.compile(r"^[a-fA-F0-9]{32,}$"),
    )

    @classmethod
    def _is_sensitive_key(cls, key: str) -> bool:
        """Check if a key name indicates sensitive data."""
        key_lower = key.lower()
        return any(pattern in key_lower for pattern in cls._SENSITIVE_KEY_PATTERNS)

    @classmethod
    def _is_sensitive_value(cls, value: str) -> bool:
        """Check if a string value looks like sensitive data."""
        if not isinstance(value, str) or len(value) < 16:
            # Short strings are unlikely to be secrets
            return False
        return any(pattern.search(value) for pattern in cls._SENSITIVE_VALUE_PATTERNS)

    @classmethod
    def _sanitize_value(cls, value: Any) -> Any:
        """Sanitize a single value, checking if it looks like sensitive data."""
        if isinstance(value, str) and cls._is_sensitive_value(value):
            return "[REDACTED]"
        return value

    @classmethod
    def _sanitize_args(cls, args: dict[str, Any]) -> dict[str, Any]:
        """Recursively sanitize sensitive data from args dictionary.

        Sanitizes based on:
        1. Key names that match sensitive patterns (case-insensitive)
        2. String values that look like secrets (API keys, tokens, etc.)
        """
        sanitized: dict[str, Any] = {}
        for k, v in args.items():
            if cls._is_sensitive_key(k):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = cls._sanitize_args(v)
            elif isinstance(v, list):
                sanitized[k] = [
                    cls._sanitize_args(item)
                    if isinstance(item, dict)
                    else cls._sanitize_value(item)
                    for item in v
                ]
            elif isinstance(v, str):
                sanitized[k] = cls._sanitize_value(v)
            else:
                sanitized[k] = v
        return sanitized

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
            details["args"] = self._sanitize_args(args)

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

    def get_observability_status(self) -> ObservabilityStatus:
        """Get the status of observability backends.

        Returns:
            ObservabilityStatus with logfire_enabled and sqlite_enabled booleans.
        """
        return ObservabilityStatus(
            logfire_enabled=self._logfire_enabled,
            sqlite_enabled=self._db is not None and self._initialized,
        )

    # Maximum allowed limit for get_recent queries (prevent excessive memory usage)
    MAX_RECENT_LIMIT = 1000

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
        # Validate limit to prevent negative values or excessive queries
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        if limit > self.MAX_RECENT_LIMIT:
            raise ValueError(f"limit must be at most {self.MAX_RECENT_LIMIT}, got {limit}")

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
        if not self._db:
            return json.dumps({"events": [], "count": 0})

        query = "SELECT * FROM audit_logs"
        conditions: list[str] = []
        params: list[Any] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type.value)

        if since:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(limit, self.MAX_RECENT_LIMIT))

        try:
            cursor = await self._db.execute(query, tuple(params))
            rows = await cursor.fetchall()

            events = []
            for row in rows:
                # Format for SIEM compatibility (CEF-like structure)
                event = {
                    "timestamp": row["created_at"],
                    "event_id": row["id"],
                    "event_type": row["event_type"],
                    "action": row["action"],
                    "target": row["target"],
                    "user": row["user"],
                    "success": bool(row["success"]),
                    "severity": "INFO" if row["success"] else "WARNING",
                    "source": "merlya",
                    "details": json.loads(row["details"]) if row["details"] else {},
                }
                events.append(event)

            return json.dumps(
                {
                    "events": events,
                    "count": len(events),
                    "exported_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            )

        except Exception as e:
            logger.warning(f"Failed to export audit logs: {e}")
            return json.dumps({"events": [], "count": 0, "error": str(e)})

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
