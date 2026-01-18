"""
Merlya Audit - Models and types.

Contains AuditEvent, AuditEventType, and related data structures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, NamedTuple


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


__all__ = [
    "AuditEvent",
    "AuditEventType",
    "ObservabilityStatus",
]
