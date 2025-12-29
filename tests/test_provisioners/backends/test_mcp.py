"""
Tests for MCP backend.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.provisioners.backends.base import BackendType
from merlya.provisioners.backends.mcp_backend import MCP_SERVERS, MCPBackend
from merlya.provisioners.base import ProvisionerAction, ProvisionerDeps
from merlya.provisioners.providers.base import InstanceSpec, ProviderType


class TestMCPServersConfig:
    """Test MCP servers configuration."""

    def test_aws_mcp_config(self) -> None:
        """Test AWS MCP configuration."""
        assert ProviderType.AWS in MCP_SERVERS
        config = MCP_SERVERS[ProviderType.AWS]
        assert config["package"] == "@aws-sdk/mcp"
        assert "create_instance" in config["tools"]
        assert "list_instances" in config["tools"]
        assert "terminate_instance" in config["tools"]

    def test_gcp_mcp_config(self) -> None:
        """Test GCP MCP configuration."""
        assert ProviderType.GCP in MCP_SERVERS
        config = MCP_SERVERS[ProviderType.GCP]
        assert config["package"] == "@google-cloud/mcp"
        assert "create_instance" in config["tools"]

    def test_azure_mcp_config(self) -> None:
        """Test Azure MCP configuration."""
        assert ProviderType.AZURE in MCP_SERVERS
        config = MCP_SERVERS[ProviderType.AZURE]
        assert config["package"] == "@azure/mcp"


class TestMCPBackendProperties:
    """Test MCP backend properties."""

    @pytest.fixture
    def backend(self) -> MCPBackend:
        """Create MCP backend."""
        ctx = MagicMock()
        ctx.mcp_manager = None
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return MCPBackend(ctx, deps)

    def test_backend_type(self, backend: MCPBackend) -> None:
        """Test backend type."""
        assert backend.backend_type == BackendType.MCP

    def test_backend_name(self, backend: MCPBackend) -> None:
        """Test backend name."""
        assert backend.name == "MCP"

    def test_capabilities(self, backend: MCPBackend) -> None:
        """Test backend capabilities."""
        caps = backend.capabilities
        assert caps.can_plan is True
        assert caps.can_diff is False  # MCP doesn't have native diff
        assert caps.can_apply is True
        assert caps.can_destroy is True
        assert caps.supports_state is False


class TestMCPAvailability:
    """Test MCP availability checking."""

    @pytest.mark.asyncio
    async def test_not_available_without_mcp_manager(self) -> None:
        """Test unavailable when no MCP manager."""
        ctx = MagicMock()
        ctx.mcp_manager = None
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        backend = MCPBackend(ctx, deps)

        assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_not_available_for_unsupported_provider(self) -> None:
        """Test unavailable for unsupported provider."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="unknown")
        backend = MCPBackend(ctx, deps)

        assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_available_with_mcp_server(self) -> None:
        """Test available when MCP server configured."""
        ctx = MagicMock()
        ctx.mcp_manager = MagicMock()
        ctx.mcp_manager.has_server = MagicMock(return_value=True)
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        backend = MCPBackend(ctx, deps)

        assert await backend.is_available() is True
        ctx.mcp_manager.has_server.assert_called_with("aws-mcp")


class TestMCPPlan:
    """Test MCP plan generation."""

    @pytest.fixture
    def backend_with_mcp(self) -> MCPBackend:
        """Create MCP backend with mocked MCP manager."""
        ctx = MagicMock()
        ctx.mcp_manager = MagicMock()
        ctx.mcp_manager.has_server = MagicMock(return_value=True)
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return MCPBackend(ctx, deps)

    @pytest.mark.asyncio
    async def test_plan_success(self, backend_with_mcp: MCPBackend) -> None:
        """Test successful plan generation."""
        specs = [
            InstanceSpec(name="web-01", image="ami-123"),
            InstanceSpec(name="web-02", image="ami-123"),
        ]

        result = await backend_with_mcp.plan(specs, ProviderType.AWS)

        assert result.success is True
        assert result.operation == "plan"
        assert result.output_data["to_create"] == 2
        assert len(result.output_data["resources"]) == 2

    @pytest.mark.asyncio
    async def test_plan_stores_specs(self, backend_with_mcp: MCPBackend) -> None:
        """Test that plan stores specs for apply."""
        specs = [InstanceSpec(name="test", image="ami-123")]
        await backend_with_mcp.plan(specs, ProviderType.AWS)

        assert backend_with_mcp._planned_specs == specs


class TestMCPApply:
    """Test MCP apply operations."""

    @pytest.fixture
    def backend_with_mcp(self) -> MCPBackend:
        """Create MCP backend with mocked MCP manager."""
        ctx = MagicMock()
        ctx.mcp_manager = MagicMock()
        ctx.mcp_manager.has_server = MagicMock(return_value=True)
        ctx.mcp_manager.call_tool = AsyncMock(
            return_value={"success": True, "instance_id": "i-12345"}
        )
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return MCPBackend(ctx, deps)

    @pytest.mark.asyncio
    async def test_apply_without_plan(self, backend_with_mcp: MCPBackend) -> None:
        """Test apply fails without plan."""
        result = await backend_with_mcp.apply()

        assert result.success is False
        assert "No plan" in result.errors[0]

    @pytest.mark.asyncio
    async def test_apply_with_plan(self, backend_with_mcp: MCPBackend) -> None:
        """Test successful apply after plan."""
        specs = [InstanceSpec(name="test-vm", image="ami-123")]
        await backend_with_mcp.plan(specs, ProviderType.AWS)

        result = await backend_with_mcp.apply()

        assert result.success is True
        assert len(result.resources_created) == 1
        assert result.rollback_data is not None


class TestMCPDestroy:
    """Test MCP destroy operations."""

    @pytest.fixture
    def backend_with_mcp(self) -> MCPBackend:
        """Create MCP backend with mocked MCP manager."""
        ctx = MagicMock()
        ctx.mcp_manager = MagicMock()
        ctx.mcp_manager.has_server = MagicMock(return_value=True)
        ctx.mcp_manager.call_tool = AsyncMock(return_value={"success": True})
        deps = ProvisionerDeps(action=ProvisionerAction.DELETE, provider="aws")
        return MCPBackend(ctx, deps)

    @pytest.mark.asyncio
    async def test_destroy_specific_resources(self, backend_with_mcp: MCPBackend) -> None:
        """Test destroying specific resources."""
        result = await backend_with_mcp.destroy(["i-12345", "i-67890"])

        assert result.success is True
        assert len(result.resources_deleted) == 2


class TestMCPRollback:
    """Test MCP rollback operations."""

    @pytest.fixture
    def backend_with_mcp(self) -> MCPBackend:
        """Create MCP backend with mocked MCP manager."""
        ctx = MagicMock()
        ctx.mcp_manager = MagicMock()
        ctx.mcp_manager.has_server = MagicMock(return_value=True)
        ctx.mcp_manager.call_tool = AsyncMock(return_value={"success": True})
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return MCPBackend(ctx, deps)

    @pytest.mark.asyncio
    async def test_rollback(self, backend_with_mcp: MCPBackend) -> None:
        """Test rollback destroys created resources."""
        rollback_data = {
            "created_resources": [
                {"instance_id": "i-123"},
                {"instance_id": "i-456"},
            ],
            "provider": "aws",
        }

        result = await backend_with_mcp.rollback(rollback_data)

        assert result.success is True
        assert len(result.resources_deleted) == 2


class TestMCPBuildArgs:
    """Test MCP tool argument building."""

    @pytest.fixture
    def backend(self) -> MCPBackend:
        """Create MCP backend."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return MCPBackend(ctx, deps)

    def test_build_aws_args(self, backend: MCPBackend) -> None:
        """Test building AWS create args."""
        spec = InstanceSpec(
            name="test-vm",
            image="ami-123",
            cpu_cores=2,
            memory_gb=4,
            subnet="subnet-456",
            security_groups=["sg-789"],
            tags={"env": "test"},
        )

        args = backend._build_create_args(spec)

        assert args["ImageId"] == "ami-123"
        assert args["InstanceType"] == "t3.medium"
        assert args["SubnetId"] == "subnet-456"
        assert args["SecurityGroupIds"] == ["sg-789"]
        assert args["TagSpecifications"][0]["Tags"][0]["Value"] == "test-vm"

    def test_build_gcp_args(self) -> None:
        """Test building GCP create args."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="gcp")
        backend = MCPBackend(ctx, deps)

        spec = InstanceSpec(
            name="gcp-vm",
            image="ubuntu-2204",
            cpu_cores=2,
            memory_gb=4,
            disk_gb=50,
            region="us-central1-a",
        )

        args = backend._build_create_args(spec)

        assert args["name"] == "gcp-vm"
        assert args["machineType"] == "e2-medium"
        assert args["sourceImage"] == "ubuntu-2204"
        assert args["diskSizeGb"] == 50
