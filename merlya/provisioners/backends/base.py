"""
Merlya Provisioners - Backend Base.

Abstract interface for IaC backend implementations.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.provisioners.base import ProvisionerDeps
    from merlya.provisioners.providers.base import InstanceSpec, ProviderType


class BackendType(str, Enum):
    """Supported backend types."""

    TERRAFORM = "terraform"
    MCP = "mcp"
    PULUMI = "pulumi"
    ANSIBLE = "ansible"
    SDK = "sdk"  # Direct SDK calls


class BackendCapabilities(BaseModel):
    """Capabilities of a backend."""

    can_plan: bool = True
    can_diff: bool = True
    can_apply: bool = True
    can_destroy: bool = True
    can_rollback: bool = True
    supports_state: bool = True
    supports_modules: bool = False
    supports_workspaces: bool = False


class BackendResult(BaseModel):
    """Result from a backend operation."""

    success: bool = False
    operation: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # Output
    stdout: str = ""
    stderr: str = ""
    output_data: dict[str, Any] = Field(default_factory=dict)

    # Resources affected
    resources_created: list[str] = Field(default_factory=list)
    resources_updated: list[str] = Field(default_factory=list)
    resources_deleted: list[str] = Field(default_factory=list)

    # Errors and warnings
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Rollback data
    rollback_data: dict[str, Any] | None = None

    def finalize(self) -> None:
        """Finalize timing."""
        self.completed_at = datetime.now(UTC)
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


class AbstractProvisionerBackend(ABC):
    """
    Abstract base class for provisioner backends.

    Backends handle the actual IaC operations (plan, apply, destroy)
    using different tools (Terraform, MCP, etc.).
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: ProvisionerDeps,
        working_dir: str | None = None,
    ) -> None:
        """
        Initialize the backend.

        Args:
            ctx: Shared context.
            deps: Provisioner dependencies.
            working_dir: Directory for IaC files.
        """
        self._ctx = ctx
        self._deps = deps
        self._working_dir = working_dir

    @property
    @abstractmethod
    def backend_type(self) -> BackendType:
        """Return the backend type."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Return backend display name."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        """Return backend capabilities."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check if the backend is available (tools installed, etc.).

        Returns:
            True if backend can be used.
        """
        ...

    @abstractmethod
    async def initialize(self) -> BackendResult:
        """
        Initialize the backend (e.g., terraform init).

        Returns:
            BackendResult with initialization status.
        """
        ...

    @abstractmethod
    async def plan(
        self,
        specs: list[InstanceSpec],
        provider: ProviderType,
    ) -> BackendResult:
        """
        Generate an execution plan.

        Args:
            specs: Instance specifications.
            provider: Target cloud provider.

        Returns:
            BackendResult with plan details.
        """
        ...

    @abstractmethod
    async def apply(self) -> BackendResult:
        """
        Apply the planned changes.

        Returns:
            BackendResult with apply status.
        """
        ...

    @abstractmethod
    async def destroy(self, resource_ids: list[str] | None = None) -> BackendResult:
        """
        Destroy resources.

        Args:
            resource_ids: Specific resources to destroy, or all if None.

        Returns:
            BackendResult with destruction status.
        """
        ...

    async def validate(self) -> BackendResult:
        """
        Validate configuration.

        Default implementation returns success.
        """
        return BackendResult(success=True, operation="validate")

    async def rollback(self, _rollback_data: dict[str, Any]) -> BackendResult:
        """
        Rollback applied changes.

        Args:
            rollback_data: Data from previous apply for rollback.

        Returns:
            BackendResult with rollback status.
        """
        return BackendResult(
            success=False,
            operation="rollback",
            errors=["Rollback not implemented for this backend"],
        )

    async def get_outputs(self) -> dict[str, Any]:
        """
        Get outputs from applied resources.

        Returns:
            Dict of output name -> value.
        """
        return {}

    async def get_state(self) -> dict[str, Any]:
        """
        Get current state.

        Returns:
            State data.
        """
        return {}


class BackendError(Exception):
    """Base exception for backend errors."""

    def __init__(
        self,
        message: str,
        backend: BackendType | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.backend = backend
        self.operation = operation
        self.details = details or {}


class BackendNotAvailableError(BackendError):
    """Raised when a backend is not available."""

    pass


class BackendExecutionError(BackendError):
    """Raised when backend execution fails."""

    pass
