"""
Tests for provisioners providers base module.

v0.9.0: Initial tests for provider abstractions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from merlya.provisioners.providers.base import (
    AbstractCloudProvider,
    CredentialsError,
    Instance,
    InstanceSpec,
    InstanceStatus,
    ProviderCapabilities,
    ProviderError,
    ProviderType,
    QuotaExceededError,
    ResourceNotFoundError,
)


class TestProviderType:
    """Test ProviderType enum."""

    def test_provider_values(self) -> None:
        """Test provider enum values."""
        assert ProviderType.AWS.value == "aws"
        assert ProviderType.GCP.value == "gcp"
        assert ProviderType.AZURE.value == "azure"
        assert ProviderType.OVH.value == "ovh"
        assert ProviderType.PROXMOX.value == "proxmox"
        assert ProviderType.VMWARE.value == "vmware"
        assert ProviderType.DIGITALOCEAN.value == "digitalocean"


class TestInstanceStatus:
    """Test InstanceStatus enum."""

    def test_status_values(self) -> None:
        """Test status enum values."""
        assert InstanceStatus.PENDING.value == "pending"
        assert InstanceStatus.RUNNING.value == "running"
        assert InstanceStatus.STOPPING.value == "stopping"
        assert InstanceStatus.STOPPED.value == "stopped"
        assert InstanceStatus.TERMINATED.value == "terminated"
        assert InstanceStatus.UNKNOWN.value == "unknown"


class TestInstanceSpec:
    """Test InstanceSpec model."""

    def test_minimal_spec(self) -> None:
        """Test minimal instance spec."""
        spec = InstanceSpec(name="test-vm", image="ami-12345")
        assert spec.name == "test-vm"
        assert spec.cpu_cores == 1
        assert spec.memory_gb == 1
        assert spec.disk_gb == 20
        assert spec.image == "ami-12345"
        assert spec.public_ip is False
        assert spec.tags == {}

    def test_full_spec(self) -> None:
        """Test full instance spec."""
        spec = InstanceSpec(
            name="web-server-01",
            cpu_cores=4,
            memory_gb=8,
            disk_gb=100,
            image="ami-ubuntu-22",
            region="us-east-1",
            network="vpc-123",
            subnet="subnet-456",
            security_groups=["sg-789"],
            public_ip=True,
            ssh_key_name="my-key",
            user_data="#!/bin/bash\necho hello",
            tags={"env": "prod", "team": "infra"},
            extra={"custom": "value"},
        )
        assert spec.cpu_cores == 4
        assert spec.memory_gb == 8
        assert spec.public_ip is True
        assert spec.tags["env"] == "prod"

    def test_to_aws_config(self) -> None:
        """Test conversion to AWS config."""
        spec = InstanceSpec(
            name="test-vm",
            cpu_cores=2,
            memory_gb=4,
            disk_gb=50,
            image="ami-12345",
            subnet="subnet-123",
            security_groups=["sg-456"],
            public_ip=True,
            ssh_key_name="my-key",
        )
        config = spec.to_provider_config(ProviderType.AWS)

        assert config["name"] == "test-vm"
        assert config["instance_type"] == "t3.medium"
        assert config["ami"] == "ami-12345"
        assert config["subnet_id"] == "subnet-123"
        assert config["vpc_security_group_ids"] == ["sg-456"]
        assert config["associate_public_ip_address"] is True
        assert config["root_block_device"]["volume_size"] == 50

    def test_to_gcp_config(self) -> None:
        """Test conversion to GCP config."""
        spec = InstanceSpec(
            name="test-vm",
            cpu_cores=2,
            memory_gb=4,
            disk_gb=50,
            image="ubuntu-2204-lts",
            region="us-central1-a",
        )
        config = spec.to_provider_config(ProviderType.GCP)

        assert config["machine_type"] == "e2-medium"
        assert config["source_image"] == "ubuntu-2204-lts"
        assert config["boot_disk_size_gb"] == 50

    def test_to_proxmox_config(self) -> None:
        """Test conversion to Proxmox config."""
        spec = InstanceSpec(
            name="test-vm",
            cpu_cores=4,
            memory_gb=8,
            disk_gb=100,
            image="ubuntu-template",
            network="vmbr1",
        )
        config = spec.to_provider_config(ProviderType.PROXMOX)

        assert config["cores"] == 4
        assert config["memory"] == 8192  # MB
        assert config["disk"] == "100G"
        assert config["clone"] == "ubuntu-template"
        assert config["network_bridge"] == "vmbr1"

    def test_aws_instance_type_mapping(self) -> None:
        """Test AWS instance type mapping."""
        # Micro
        spec = InstanceSpec(name="t", cpu_cores=1, memory_gb=1, image="a")
        assert spec._aws_instance_type() == "t3.micro"

        # Medium
        spec = InstanceSpec(name="t", cpu_cores=2, memory_gb=4, image="a")
        assert spec._aws_instance_type() == "t3.medium"

        # Large
        spec = InstanceSpec(name="t", cpu_cores=4, memory_gb=8, image="a")
        assert spec._aws_instance_type() == "t3.large"

        # XLarge
        spec = InstanceSpec(name="t", cpu_cores=8, memory_gb=16, image="a")
        assert spec._aws_instance_type() == "t3.xlarge"


class TestInstance:
    """Test Instance model."""

    def test_basic_instance(self) -> None:
        """Test basic instance creation."""
        instance = Instance(
            id="i-12345",
            name="web-01",
            provider=ProviderType.AWS,
            status=InstanceStatus.RUNNING,
            public_ip="54.1.2.3",
            private_ip="10.0.0.5",
            region="us-east-1a",
            tags={"env": "prod"},
        )
        assert instance.id == "i-12345"
        assert instance.status == InstanceStatus.RUNNING
        assert instance.public_ip == "54.1.2.3"

    def test_from_aws(self) -> None:
        """Test creating instance from AWS response."""
        aws_data = {
            "InstanceId": "i-abc123",
            "State": {"Name": "running"},
            "PublicIpAddress": "54.10.20.30",
            "PrivateIpAddress": "10.0.1.50",
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "Tags": [
                {"Key": "Name", "Value": "web-server"},
                {"Key": "env", "Value": "prod"},
            ],
            "LaunchTime": datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
        }

        instance = Instance.from_aws(aws_data)
        assert instance.id == "i-abc123"
        assert instance.name == "web-server"
        assert instance.provider == ProviderType.AWS
        assert instance.status == InstanceStatus.RUNNING
        assert instance.public_ip == "54.10.20.30"
        assert instance.private_ip == "10.0.1.50"
        assert instance.tags["env"] == "prod"

    def test_from_aws_all_states(self) -> None:
        """Test AWS state mapping."""
        states = {
            "pending": InstanceStatus.PENDING,
            "running": InstanceStatus.RUNNING,
            "stopping": InstanceStatus.STOPPING,
            "stopped": InstanceStatus.STOPPED,
            "terminated": InstanceStatus.TERMINATED,
        }

        for aws_state, expected_status in states.items():
            aws_data = {
                "InstanceId": "i-test",
                "State": {"Name": aws_state},
                "Tags": [],
            }
            instance = Instance.from_aws(aws_data)
            assert instance.status == expected_status

    def test_from_gcp(self) -> None:
        """Test creating instance from GCP response."""
        gcp_data = {
            "id": "123456789",
            "name": "gcp-vm-01",
            "status": "RUNNING",
            "zone": "projects/my-project/zones/us-central1-a",
            "networkInterfaces": [
                {
                    "networkIP": "10.128.0.5",
                    "accessConfigs": [{"natIP": "35.192.0.100"}],
                }
            ],
            "labels": {"env": "staging"},
        }

        instance = Instance.from_gcp(gcp_data)
        assert instance.id == "123456789"
        assert instance.name == "gcp-vm-01"
        assert instance.provider == ProviderType.GCP
        assert instance.status == InstanceStatus.RUNNING
        assert instance.public_ip == "35.192.0.100"
        assert instance.private_ip == "10.128.0.5"
        assert instance.region == "us-central1-a"


class TestProviderCapabilities:
    """Test ProviderCapabilities model."""

    def test_default_capabilities(self) -> None:
        """Test default capabilities."""
        caps = ProviderCapabilities()
        assert caps.can_create is True
        assert caps.can_update is True
        assert caps.can_delete is True
        assert caps.supports_vpc is True
        assert caps.has_mcp_support is False
        assert caps.has_terraform_support is True

    def test_custom_capabilities(self) -> None:
        """Test custom capabilities."""
        caps = ProviderCapabilities(
            has_mcp_support=True,
            supports_auto_scaling=True,
            can_snapshot=False,
        )
        assert caps.has_mcp_support is True
        assert caps.supports_auto_scaling is True
        assert caps.can_snapshot is False


class TestProviderErrors:
    """Test provider error classes."""

    def test_provider_error(self) -> None:
        """Test base provider error."""
        error = ProviderError(
            "Something went wrong",
            provider=ProviderType.AWS,
            operation="create_instance",
            details={"instance_id": "i-123"},
        )
        assert "Something went wrong" in str(error)
        assert error.provider == ProviderType.AWS
        assert error.operation == "create_instance"
        assert error.details["instance_id"] == "i-123"

    def test_credentials_error(self) -> None:
        """Test credentials error."""
        error = CredentialsError(
            "Missing AWS_ACCESS_KEY_ID",
            provider=ProviderType.AWS,
        )
        assert isinstance(error, ProviderError)
        assert "Missing" in str(error)

    def test_resource_not_found_error(self) -> None:
        """Test resource not found error."""
        error = ResourceNotFoundError(
            "Instance i-123 not found",
            provider=ProviderType.AWS,
            operation="get_instance",
        )
        assert isinstance(error, ProviderError)

    def test_quota_exceeded_error(self) -> None:
        """Test quota exceeded error."""
        error = QuotaExceededError(
            "vCPU limit reached",
            provider=ProviderType.AWS,
        )
        assert isinstance(error, ProviderError)


class ConcreteProvider(AbstractCloudProvider):
    """Concrete provider for testing."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.AWS

    @property
    def name(self) -> str:
        return "Test Provider"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def validate_credentials(self) -> tuple[bool, str | None]:
        return True, None

    async def list_instances(self, filters: dict[str, Any] | None = None) -> list[Instance]:
        return []

    async def get_instance(self, instance_id: str) -> Instance | None:
        return None

    async def create_instance(self, spec: InstanceSpec) -> Instance:
        return Instance(
            id="i-test",
            name=spec.name,
            provider=ProviderType.AWS,
            status=InstanceStatus.PENDING,
        )

    async def update_instance(self, instance_id: str, updates: dict[str, Any]) -> Instance:
        return Instance(
            id=instance_id,
            name="updated",
            provider=ProviderType.AWS,
        )

    async def delete_instance(self, instance_id: str) -> bool:
        return True

    async def start_instance(self, instance_id: str) -> Instance:
        return Instance(
            id=instance_id,
            name="test",
            provider=ProviderType.AWS,
            status=InstanceStatus.RUNNING,
        )

    async def stop_instance(self, instance_id: str) -> Instance:
        return Instance(
            id=instance_id,
            name="test",
            provider=ProviderType.AWS,
            status=InstanceStatus.STOPPED,
        )


class TestAbstractCloudProvider:
    """Test AbstractCloudProvider base class."""

    @pytest.fixture
    def provider(self) -> ConcreteProvider:
        """Create concrete provider instance."""
        from unittest.mock import MagicMock

        ctx = MagicMock()
        return ConcreteProvider(ctx)

    @pytest.mark.asyncio
    async def test_create_instance(self, provider: ConcreteProvider) -> None:
        """Test instance creation."""
        spec = InstanceSpec(name="test-vm", image="ami-123")
        instance = await provider.create_instance(spec)
        assert instance.name == "test-vm"
        assert instance.status == InstanceStatus.PENDING

    @pytest.mark.asyncio
    async def test_start_instance(self, provider: ConcreteProvider) -> None:
        """Test starting instance."""
        instance = await provider.start_instance("i-123")
        assert instance.status == InstanceStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stop_instance(self, provider: ConcreteProvider) -> None:
        """Test stopping instance."""
        instance = await provider.stop_instance("i-123")
        assert instance.status == InstanceStatus.STOPPED

    @pytest.mark.asyncio
    async def test_delete_instance(self, provider: ConcreteProvider) -> None:
        """Test deleting instance."""
        result = await provider.delete_instance("i-123")
        assert result is True

    def test_provider_properties(self, provider: ConcreteProvider) -> None:
        """Test provider properties."""
        assert provider.provider_type == ProviderType.AWS
        assert provider.name == "Test Provider"
        assert isinstance(provider.capabilities, ProviderCapabilities)
