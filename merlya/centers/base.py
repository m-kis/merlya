"""
Merlya Centers - Base Classes.

Defines the core abstractions for operational centers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host


class CenterMode(str, Enum):
    """Operational mode for centers."""

    DIAGNOSTIC = "diagnostic"  # Read-only investigation
    CHANGE = "change"  # Controlled mutations


class RiskLevel(str, Enum):
    """Risk level for operations."""

    LOW = "low"  # Safe, read-only
    MEDIUM = "medium"  # Might reveal sensitive info
    HIGH = "high"  # Modifies state, requires HITL
    CRITICAL = "critical"  # Destructive, requires explicit confirmation


class LocalHost:
    """Pseudo-host representing the local machine."""

    name: str = "local"
    hostname: str = "localhost"
    is_local: bool = True

    def __init__(self) -> None:
        """Initialize local host."""
        self.name = "local"
        self.hostname = "localhost"
        self.is_local = True


class CenterDeps(BaseModel):
    """Dependencies passed to center execution."""

    model_config = {"arbitrary_types_allowed": True}

    target: str  # Host name or target identifier
    task: str  # User's request
    host: Any = None  # Resolved host (optional, uses Any to avoid import cycle)
    extra: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    """Evidence collected during diagnostic operations."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    host: str
    command: str
    output: str
    exit_code: int
    duration_ms: int


class CenterResult(BaseModel):
    """Result from center execution."""

    success: bool
    message: str
    mode: CenterMode
    evidence: list[Evidence] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    # For CHANGE operations
    applied: bool = False
    rollback_available: bool = False
    post_check_passed: bool | None = None

    # Timing
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int = 0


class AbstractCenter(ABC):
    """
    Abstract base class for operational centers.

    Centers are the main operational units that handle either
    DIAGNOSTIC (read-only) or CHANGE (mutation) operations.
    """

    def __init__(self, ctx: SharedContext):
        """
        Initialize center with shared context.

        Args:
            ctx: Shared context with infrastructure access.
        """
        self._ctx = ctx

    @property
    @abstractmethod
    def mode(self) -> CenterMode:
        """Get the center's operational mode."""
        ...

    @property
    @abstractmethod
    def allowed_tools(self) -> list[str]:
        """Get list of tools this center is allowed to use."""
        ...

    @abstractmethod
    async def execute(self, deps: CenterDeps) -> CenterResult:
        """
        Execute the center's main operation.

        Args:
            deps: Dependencies and context for execution.

        Returns:
            Result of the operation.
        """
        ...

    @property
    def risk_level(self) -> RiskLevel:
        """Get default risk level for this center."""
        if self.mode == CenterMode.DIAGNOSTIC:
            return RiskLevel.LOW
        return RiskLevel.HIGH

    async def validate_target(self, target: str) -> Host | LocalHost | None:
        """
        Validate and resolve target host.

        Args:
            target: Host name or pattern (may include @ prefix).

        Returns:
            Resolved Host, LocalHost for local targets, or None if not found.
        """
        # Strip @ prefix if present (users may type "@pine64" to reference a host)
        clean_target = target.lstrip("@")

        # Handle "local" target specially - no database lookup needed
        if clean_target.lower() in ("local", "localhost", "127.0.0.1", "::1"):
            return LocalHost()

        try:
            return await self._ctx.hosts.get_by_name(clean_target)
        except Exception:
            return None

    def _create_result(
        self,
        success: bool,
        message: str,
        evidence: list[Evidence] | None = None,
        **kwargs: Any,
    ) -> CenterResult:
        """Helper to create a CenterResult."""
        return CenterResult(
            success=success,
            message=message,
            mode=self.mode,
            evidence=evidence or [],
            **kwargs,
        )
