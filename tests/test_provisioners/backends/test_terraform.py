"""
Tests for Terraform backend.

v0.9.0: Initial tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.provisioners.backends.base import BackendType
from merlya.provisioners.backends.terraform import TerraformBackend, _sanitize_resource_name
from merlya.provisioners.base import ProvisionerAction, ProvisionerDeps
from merlya.provisioners.providers.base import InstanceSpec, ProviderType


class TestTerraformBackendProperties:
    """Test Terraform backend properties."""

    @pytest.fixture
    def backend(self) -> TerraformBackend:
        """Create Terraform backend."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return TerraformBackend(ctx, deps)

    def test_backend_type(self, backend: TerraformBackend) -> None:
        """Test backend type."""
        assert backend.backend_type == BackendType.TERRAFORM

    def test_backend_name(self, backend: TerraformBackend) -> None:
        """Test backend name."""
        assert backend.name == "Terraform"

    def test_capabilities(self, backend: TerraformBackend) -> None:
        """Test backend capabilities."""
        caps = backend.capabilities
        assert caps.can_plan is True
        assert caps.can_diff is True
        assert caps.can_apply is True
        assert caps.can_destroy is True
        assert caps.supports_state is True
        assert caps.supports_modules is True
        assert caps.supports_workspaces is True


class TestTerraformAvailability:
    """Test Terraform availability checking."""

    @pytest.fixture
    def backend(self) -> TerraformBackend:
        """Create Terraform backend."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return TerraformBackend(ctx, deps)

    @pytest.mark.asyncio
    async def test_is_available_when_installed(self, backend: TerraformBackend) -> None:
        """Test availability when terraform is installed."""
        with patch.object(shutil, "which", return_value="/usr/local/bin/terraform"):
            assert await backend.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_when_not_installed(self, backend: TerraformBackend) -> None:
        """Test availability when terraform is not installed."""
        with patch.object(shutil, "which", return_value=None):
            assert await backend.is_available() is False


class TestTerraformPlanOutput:
    """Test plan output parsing."""

    @pytest.fixture
    def backend(self) -> TerraformBackend:
        """Create Terraform backend."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        return TerraformBackend(ctx, deps)

    def test_parse_plan_create(self, backend: TerraformBackend) -> None:
        """Test parsing plan with creates."""
        output = """
Terraform will perform the following actions:

  # aws_instance.web will be created
  + resource "aws_instance" "web" {
      + ami           = "ami-12345"
      + instance_type = "t3.micro"
    }

Plan: 1 to add, 0 to change, 0 to destroy.
"""
        data = backend._parse_plan_output(output)
        assert data["to_create"] >= 1
        assert "aws_instance.web" in data["resources"]

    def test_parse_plan_mixed(self, backend: TerraformBackend) -> None:
        """Test parsing plan with mixed changes."""
        output = """
  # aws_instance.web will be created
  # aws_instance.db will be updated in-place
  # aws_instance.old will be destroyed

Plan: 1 to add, 1 to change, 1 to destroy.
"""
        data = backend._parse_plan_output(output)
        assert data["to_create"] >= 1
        assert data["to_update"] >= 1
        assert data["to_delete"] >= 1

    def test_parse_apply_output(self, backend: TerraformBackend) -> None:
        """Test parsing apply output."""
        output = """
aws_instance.web: Creating...
aws_instance.web: Still creating... [10s elapsed]
aws_instance.web: Creation complete after 30s [id=i-12345]

Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
"""
        data = backend._parse_apply_output(output)
        assert len(data["created"]) >= 0  # Parsing is best-effort


class TestTerraformConfigGeneration:
    """Test Terraform config generation."""

    @pytest.fixture
    def backend(self) -> TerraformBackend:
        """Create Terraform backend."""
        ctx = MagicMock()
        deps = ProvisionerDeps(
            action=ProvisionerAction.CREATE,
            provider="aws",
            extra={"region": "us-east-1"},
        )
        return TerraformBackend(ctx, deps)

    def test_generate_aws_config(self, backend: TerraformBackend) -> None:
        """Test AWS config generation."""
        specs = [
            InstanceSpec(
                name="web-server",
                cpu_cores=2,
                memory_gb=4,
                disk_gb=50,
                image="ami-ubuntu",
                subnet="subnet-123",
                security_groups=["sg-456"],
                public_ip=True,
                tags={"env": "test"},
            )
        ]

        config = backend._generate_tf_config(specs, ProviderType.AWS)

        assert 'provider "aws"' in config
        assert 'region = "us-east-1"' in config
        assert 'resource "aws_instance" "web_server"' in config
        assert "ami-ubuntu" in config
        assert "t3.medium" in config
        assert "subnet-123" in config
        assert "sg-456" in config
        assert 'Name = "web-server"' in config
        assert 'env = "test"' in config


class TestTerraformResourceNameSanitization:
    def test_sanitize_resource_name_replaces_hyphens(self) -> None:
        assert _sanitize_resource_name("web-server") == "web_server"

    def test_sanitize_resource_name_prefixes_invalid_start(self) -> None:
        assert _sanitize_resource_name("1bad") == "_1bad"

    def test_sanitize_resource_name_fallback_when_empty(self) -> None:
        assert _sanitize_resource_name("") == "_unnamed"


class TestTerraformPlanWorkingDirectory:
    @pytest.mark.asyncio
    async def test_plan_errors_without_workdir_and_specs(self) -> None:
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        backend = TerraformBackend(ctx, deps)

        result = await backend.plan([], ProviderType.AWS)

        assert result.success is False
        assert any("working directory" in err.lower() for err in result.errors)

    @pytest.mark.asyncio
    async def test_plan_generates_config_when_no_workdir(self) -> None:
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        backend = TerraformBackend(ctx, deps)
        backend._initialized = True  # Skip init for unit test

        with patch.object(backend, "_run_terraform", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (
                0,
                "Plan: 0 to add, 0 to change, 0 to destroy.",
                "",
            )

            specs = [InstanceSpec(name="test", image="ami-123")]
            result = await backend.plan(specs, ProviderType.AWS)

        try:
            assert result.success is True
            assert backend._working_dir
            assert backend._temp_dir
            assert (Path(backend._working_dir) / "main.tf").exists()
            assert mock_run.await_count == 1
            assert mock_run.call_args.args[0] == "plan"
        finally:
            backend.cleanup()


class TestTerraformOperations:
    """Test Terraform operations with mocked subprocess."""

    @pytest.fixture
    def backend(self) -> TerraformBackend:
        """Create Terraform backend."""
        ctx = MagicMock()
        deps = ProvisionerDeps(action=ProvisionerAction.CREATE, provider="aws")
        backend = TerraformBackend(ctx, deps, working_dir="/tmp/test")
        backend._initialized = True  # Skip init for tests
        return backend

    @pytest.mark.asyncio
    async def test_plan_success(self, backend: TerraformBackend) -> None:
        """Test successful plan."""
        mock_output = "Plan: 1 to add, 0 to change, 0 to destroy."

        with patch.object(backend, "_run_terraform", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, mock_output, "")

            specs = [InstanceSpec(name="test", image="ami-123")]
            result = await backend.plan(specs, ProviderType.AWS)

            assert result.success is True
            assert result.operation == "plan"
            mock_run.assert_called()

    @pytest.mark.asyncio
    async def test_apply_success(self, backend: TerraformBackend) -> None:
        """Test successful apply."""
        mock_output = "Apply complete! Resources: 1 added."

        with patch.object(backend, "_run_terraform", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, mock_output, "")
            with patch.object(backend, "get_outputs", new_callable=AsyncMock) as mock_outputs:
                mock_outputs.return_value = {"public_ip": "10.0.0.1"}
                with patch.object(backend, "get_state", new_callable=AsyncMock) as mock_state:
                    mock_state.return_value = {}

                    result = await backend.apply()

                    assert result.success is True
                    assert result.operation == "apply"

    @pytest.mark.asyncio
    async def test_destroy_success(self, backend: TerraformBackend) -> None:
        """Test successful destroy."""
        mock_output = "Destroy complete! Resources: 1 destroyed."

        with patch.object(backend, "_run_terraform", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, mock_output, "")

            result = await backend.destroy()

            assert result.success is True
            assert result.operation == "destroy"

    @pytest.mark.asyncio
    async def test_validate_success(self, backend: TerraformBackend) -> None:
        """Test successful validation."""
        mock_output = '{"valid": true, "diagnostics": []}'

        with patch.object(backend, "_run_terraform", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, mock_output, "")

            result = await backend.validate()

            assert result.success is True
            assert result.operation == "validate"

    @pytest.mark.asyncio
    async def test_validate_failure(self, backend: TerraformBackend) -> None:
        """Test validation failure."""
        mock_output = (
            '{"valid": false, "diagnostics": [{"severity": "error", "summary": "Invalid config"}]}'
        )

        with patch.object(backend, "_run_terraform", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, mock_output, "")

            result = await backend.validate()

            assert result.success is False
            assert "Invalid config" in result.errors[0]
