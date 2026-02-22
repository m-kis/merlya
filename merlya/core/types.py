"""
Merlya Core - Shared types and enums.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AgentMode(StrEnum):
    """Agent operating mode."""

    DIAGNOSTIC = "diagnostic"
    REMEDIATION = "remediation"
    QUERY = "query"
    CHAT = "chat"


class CheckStatus(StrEnum):
    """Health check status."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    DISABLED = "disabled"


class HostStatus(StrEnum):
    """Host health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class Priority(StrEnum):
    """Alert priority levels."""

    P0 = "P0"  # Critical
    P1 = "P1"  # Urgent
    P2 = "P2"  # Normal
    P3 = "P3"  # Low


class RiskLevel(StrEnum):
    """Command risk level for confirmation."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    """Result of a health check."""

    name: str
    status: CheckStatus
    message: str
    critical: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    host: str | None = None
    command: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def output(self) -> str:
        """Combined stdout and stderr."""
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}".strip()
        return self.stdout
