"""
Tests for provisioners backends base module.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from merlya.provisioners.backends.base import (
    AbstractProvisionerBackend,
    BackendCapabilities,
    BackendError,
    BackendExecutionError,
    BackendNotAvailableError,
    BackendResult,
    BackendType,
)
from merlya.provisioners.base import ProvisionerAction, ProvisionerDeps
from merlya.provisioners.providers.base import InstanceSpec, ProviderType


class TestBackendType:
    """Test BackendType enum."""

    def test_backend_values(self) -> None:
        """Test backend enum values."""
        assert BackendType.TERRAFORM.value == "terraform"
        assert BackendType.MCP.value == "mcp"
        assert BackendType.PULUMI.value == "pulumi"
        assert BackendType.ANSIBLE.value == "ansible"
        assert BackendType.SDK.value == "sdk"


class TestBackendCapabilities:
    """Test BackendCapabilities model."""

    def test_default_capabilities(self) -> None:
        """Test default capabilities."""
        caps = BackendCapabilities()
        assert caps.can_plan is True
        assert caps.can_diff is True
        assert caps.can_apply is True
        assert caps.can_destroy is True
        assert caps.can_rollback is True
        assert caps.supports_state is True
        assert caps.supports_modules is False

    def test_custom_capabilities(self) -> None:
        """Test custom capabilities."""
        caps = BackendCapabilities(
            can_diff=False,
            supports_modules=True,
            supports_workspaces=True,
        )
        assert caps.can_diff is False
        assert caps.supports_modules is True
        assert caps.supports_workspaces is True


class TestBackendResult:
    """Test BackendResult model."""

    def test_default_result(self) -> None:
        """Test default result values."""
        result = BackendResult(operation="test")
        assert result.success is False
        assert result.operation == "test"
        assert result.resources_created == []
        assert result.errors == []

    def test_successful_result(self) -> None:
        """Test successful result."""
        result = BackendResult(
            success=True,
            operation="apply",
            stdout="Applied successfully",
            resources_created=["instance.web-01"],
            output_data={"public_ip": "10.0.0.1"},
        )
        assert result.success is True
        assert result.resources_created == ["instance.web-01"]
        assert result.output_data["public_ip"] == "10.0.0.1"

    def test_finalize(self) -> None:
        """Test result finalization."""
        result = BackendResult(operation="test")
        result.finalize()

        assert result.completed_at is not None
        assert result.duration_seconds >= 0


class TestBackendErrors:
    """Test backend error classes."""

    def test_backend_error(self) -> None:
        """Test base backend error."""
        error = BackendError(
            "Something failed",
            backend=BackendType.TERRAFORM,
            operation="apply",
            details={"code": 1},
        )
        assert "Something failed" in str(error)
        assert error.backend == BackendType.TERRAFORM
        assert error.operation == "apply"
        assert error.details["code"] == 1

    def test_not_available_error(self) -> None:
        """Test not available error."""
        error = BackendNotAvailableError(
            "Terraform not installed",
            backend=BackendType.TERRAFORM,
        )
        assert isinstance(error, BackendError)

    def test_execution_error(self) -> None:
        """Test execution error."""
        error = BackendExecutionError(
            "Plan failed",
            backend=BackendType.TERRAFORM,
            operation="plan",
        )
        assert isinstance(error, BackendError)


class ConcreteBackend(AbstractProvisionerBackend):
    """Concrete backend for testing."""

    @property
    def backend_type(self) -> BackendType:
        return BackendType.TERRAFORM

    @property
    def name(self) -> str:
        return "Test Backend"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities()

    async def is_available(self) -> bool:
        return True

    async def initialize(self) -> BackendResult:
        return BackendResult(success=True, operation="init")

    async def plan(self, specs: list[InstanceSpec], provider: ProviderType) -> BackendResult:
        return BackendResult(
            success=True,
            operation="plan",
            output_data={"to_create": len(specs)},
        )

    async def apply(self) -> BackendResult:
        return BackendResult(
            success=True,
            operation="apply",
            resources_created=["instance.test"],
        )

    async def destroy(self, resource_ids: list[str] | None = None) -> BackendResult:
        return BackendResult(
            success=True,
            operation="destroy",
            resources_deleted=resource_ids or ["instance.test"],
        )


class TestAbstractProvisionerBackend:
    """Test AbstractProvisionerBackend base class."""

    @pytest.fixture
    def mock_ctx(self) -> MagicMock:
        """Create mock context."""
        return MagicMock()

    @pytest.fixture
    def deps(self) -> ProvisionerDeps:
        """Create test dependencies."""
        return ProvisionerDeps(
            action=ProvisionerAction.CREATE,
            provider="aws",
        )

    @pytest.fixture
    def backend(self, mock_ctx: MagicMock, deps: ProvisionerDeps) -> ConcreteBackend:
        """Create concrete backend instance."""
        return ConcreteBackend(mock_ctx, deps)

    @pytest.mark.asyncio
    async def test_is_available(self, backend: ConcreteBackend) -> None:
        """Test availability check."""
        assert await backend.is_available() is True

    @pytest.mark.asyncio
    async def test_initialize(self, backend: ConcreteBackend) -> None:
        """Test initialization."""
        result = await backend.initialize()
        assert result.success is True
        assert result.operation == "init"

    @pytest.mark.asyncio
    async def test_plan(self, backend: ConcreteBackend) -> None:
        """Test plan generation."""
        specs = [InstanceSpec(name="test-vm", image="ami-123")]
        result = await backend.plan(specs, ProviderType.AWS)

        assert result.success is True
        assert result.operation == "plan"
        assert result.output_data["to_create"] == 1

    @pytest.mark.asyncio
    async def test_apply(self, backend: ConcreteBackend) -> None:
        """Test apply."""
        result = await backend.apply()

        assert result.success is True
        assert result.operation == "apply"
        assert "instance.test" in result.resources_created

    @pytest.mark.asyncio
    async def test_destroy(self, backend: ConcreteBackend) -> None:
        """Test destroy."""
        result = await backend.destroy(["instance.web-01"])

        assert result.success is True
        assert result.operation == "destroy"
        assert "instance.web-01" in result.resources_deleted

    @pytest.mark.asyncio
    async def test_validate_default(self, backend: ConcreteBackend) -> None:
        """Test default validate implementation."""
        result = await backend.validate()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_rollback_default(self, backend: ConcreteBackend) -> None:
        """Test default rollback implementation."""
        result = await backend.rollback({})
        assert result.success is False
        assert "not implemented" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_get_outputs_default(self, backend: ConcreteBackend) -> None:
        """Test default get_outputs implementation."""
        outputs = await backend.get_outputs()
        assert outputs == {}

    @pytest.mark.asyncio
    async def test_get_state_default(self, backend: ConcreteBackend) -> None:
        """Test default get_state implementation."""
        state = await backend.get_state()
        assert state == {}

    def test_backend_properties(self, backend: ConcreteBackend) -> None:
        """Test backend properties."""
        assert backend.backend_type == BackendType.TERRAFORM
        assert backend.name == "Test Backend"
        assert isinstance(backend.capabilities, BackendCapabilities)
