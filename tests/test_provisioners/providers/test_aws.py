"""
Tests for AWS cloud provider.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.provisioners.providers.aws import AWSProvider
from merlya.provisioners.providers.base import (
    InstanceSpec,
    InstanceStatus,
    ProviderType,
)


class TestAWSProviderProperties:
    """Test AWS provider properties."""

    @pytest.fixture
    def provider(self) -> AWSProvider:
        """Create AWS provider."""
        ctx = MagicMock()
        return AWSProvider(ctx)

    def test_provider_type(self, provider: AWSProvider) -> None:
        """Test provider type."""
        assert provider.provider_type == ProviderType.AWS

    def test_provider_name(self, provider: AWSProvider) -> None:
        """Test provider name."""
        assert provider.name == "Amazon Web Services"

    def test_capabilities(self, provider: AWSProvider) -> None:
        """Test provider capabilities."""
        caps = provider.capabilities
        assert caps.can_create is True
        assert caps.can_update is True
        assert caps.can_delete is True
        assert caps.has_mcp_support is True
        assert caps.has_terraform_support is True
        assert caps.supports_vpc is True
        assert caps.can_snapshot is False
        assert caps.supports_object_storage is False
        assert caps.supports_auto_scaling is False
        assert caps.supports_load_balancing is False
        assert caps.supports_dns is False

    def test_capabilities_match_implemented_methods(self, provider: AWSProvider) -> None:
        """Assert capability flags match implemented methods."""

        def _has_all_methods(method_names: tuple[str, ...]) -> bool:
            for method_name in method_names:
                attr = getattr(provider, method_name, None)
                if not callable(attr):
                    return False
            return True

        expected_methods: dict[str, tuple[str, ...]] = {
            "can_snapshot": (
                "create_snapshot",
                "list_snapshots",
                "delete_snapshot",
            ),
            "supports_object_storage": (
                "list_buckets",
                "create_bucket",
                "delete_bucket",
                "put_object",
                "get_object",
                "delete_object",
            ),
            "supports_auto_scaling": (
                "create_auto_scaling_group",
                "list_auto_scaling_groups",
                "update_auto_scaling_group",
                "delete_auto_scaling_group",
            ),
            "supports_load_balancing": (
                "create_load_balancer",
                "list_load_balancers",
                "delete_load_balancer",
            ),
            "supports_dns": (
                "create_dns_record",
                "list_dns_records",
                "delete_dns_record",
            ),
        }

        caps = provider.capabilities
        for capability_name, method_names in expected_methods.items():
            implemented = _has_all_methods(method_names)
            assert getattr(caps, capability_name) == implemented


class TestAWSProviderCredentials:
    """Test AWS credential validation."""

    @pytest.fixture
    def provider(self) -> AWSProvider:
        """Create AWS provider."""
        ctx = MagicMock()
        return AWSProvider(ctx)

    @pytest.mark.asyncio
    async def test_missing_credentials(self, provider: AWSProvider) -> None:
        """Test validation with missing credentials."""
        with patch("merlya.provisioners.providers.aws.CredentialResolver") as mock_resolver:
            mock_instance = MagicMock()
            mock_instance.resolve.return_value = MagicMock(
                is_complete=False,
                missing=["AWS_ACCESS_KEY_ID"],
            )
            mock_resolver.get_instance.return_value = mock_instance
            provider._credential_resolver = mock_instance

            success, error = await provider.validate_credentials()
            assert success is False
            assert "credentials" in error.lower()


class TestAWSProviderOperations:
    """Test AWS provider operations with mocked boto3."""

    @pytest.fixture
    def mock_boto3_client(self) -> MagicMock:
        """Create mock boto3 EC2 client."""
        client = MagicMock()
        client.describe_regions.return_value = {
            "Regions": [{"RegionName": "us-east-1"}, {"RegionName": "eu-west-1"}]
        }
        return client

    @pytest.fixture
    def provider_with_client(self, mock_boto3_client: MagicMock) -> AWSProvider:
        """Create AWS provider with mocked client."""
        ctx = MagicMock()
        provider = AWSProvider(ctx)
        provider._client = mock_boto3_client
        provider._region = "us-east-1"
        return provider

    @pytest.mark.asyncio
    async def test_list_instances(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test listing instances."""
        mock_boto3_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-abc123",
                            "State": {"Name": "running"},
                            "Tags": [{"Key": "Name", "Value": "web-01"}],
                        }
                    ]
                }
            ]
        }

        instances = await provider_with_client.list_instances()

        assert len(instances) == 1
        assert instances[0].id == "i-abc123"
        assert instances[0].name == "web-01"
        assert instances[0].status == InstanceStatus.RUNNING

    @pytest.mark.asyncio
    async def test_list_instances_uses_to_thread(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Ensure boto3 calls don't block the event loop."""
        mock_boto3_client.describe_instances.return_value = {"Reservations": []}

        with patch(
            "merlya.provisioners.providers.aws.asyncio.to_thread",
            new_callable=AsyncMock,
        ) as mock_to_thread:
            mock_to_thread.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
            await provider_with_client.list_instances()
            assert mock_to_thread.await_count >= 1

    @pytest.mark.asyncio
    async def test_list_instances_warns_on_unsupported_filters(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Unsupported filter keys should not be silently ignored."""
        mock_boto3_client.describe_instances.return_value = {"Reservations": []}

        with (
            patch(
                "merlya.provisioners.providers.aws.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread,
            patch("merlya.provisioners.providers.aws.logger.warning") as warn,
        ):
            mock_to_thread.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
            await provider_with_client.list_instances(filters={"unsupported": "x"})
            warn.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_instances_with_filters(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test listing instances with filters."""
        mock_boto3_client.describe_instances.return_value = {"Reservations": []}

        await provider_with_client.list_instances(filters={"status": "running"})

        mock_boto3_client.describe_instances.assert_called_once()
        call_args = mock_boto3_client.describe_instances.call_args
        filters = call_args.kwargs["Filters"]
        assert any(f["Name"] == "instance-state-name" for f in filters)

    @pytest.mark.asyncio
    async def test_get_instance(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test getting a single instance."""
        mock_boto3_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-xyz789",
                            "State": {"Name": "stopped"},
                            "Tags": [{"Key": "Name", "Value": "db-01"}],
                        }
                    ]
                }
            ]
        }

        instance = await provider_with_client.get_instance("i-xyz789")

        assert instance is not None
        assert instance.id == "i-xyz789"
        assert instance.status == InstanceStatus.STOPPED

    @pytest.mark.asyncio
    async def test_get_instance_not_found(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test getting non-existent instance."""
        mock_boto3_client.describe_instances.return_value = {"Reservations": []}

        instance = await provider_with_client.get_instance("i-nonexistent")

        assert instance is None

    @pytest.mark.asyncio
    async def test_create_instance(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test creating an instance."""
        mock_boto3_client.run_instances.return_value = {
            "Instances": [
                {
                    "InstanceId": "i-new123",
                    "State": {"Name": "pending"},
                    "Tags": [{"Key": "Name", "Value": "test-vm"}],
                }
            ]
        }

        spec = InstanceSpec(
            name="test-vm",
            cpu_cores=2,
            memory_gb=4,
            disk_gb=50,
            image="ami-ubuntu",
            subnet="subnet-123",
            public_ip=True,
            tags={"env": "test"},
        )

        instance = await provider_with_client.create_instance(spec)

        assert instance.id == "i-new123"
        assert instance.status == InstanceStatus.PENDING
        mock_boto3_client.run_instances.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_instance(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test deleting an instance."""
        mock_boto3_client.terminate_instances.return_value = {}

        result = await provider_with_client.delete_instance("i-todelete")

        assert result is True
        mock_boto3_client.terminate_instances.assert_called_once_with(InstanceIds=["i-todelete"])

    @pytest.mark.asyncio
    async def test_start_instance(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test starting an instance."""
        mock_boto3_client.start_instances.return_value = {}
        mock_boto3_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-123",
                            "State": {"Name": "running"},
                            "Tags": [],
                        }
                    ]
                }
            ]
        }

        instance = await provider_with_client.start_instance("i-123")

        assert instance.status == InstanceStatus.RUNNING
        mock_boto3_client.start_instances.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_instance(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test stopping an instance."""
        mock_boto3_client.stop_instances.return_value = {}
        mock_boto3_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-123",
                            "State": {"Name": "stopped"},
                            "Tags": [],
                        }
                    ]
                }
            ]
        }

        instance = await provider_with_client.stop_instance("i-123")

        assert instance.status == InstanceStatus.STOPPED
        mock_boto3_client.stop_instances.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_regions(
        self, provider_with_client: AWSProvider, mock_boto3_client: MagicMock
    ) -> None:
        """Test listing regions."""
        regions = await provider_with_client.list_regions()

        assert "us-east-1" in regions
        assert "eu-west-1" in regions


class TestAWSInstanceSpecMapping:
    """Test InstanceSpec to AWS config mapping."""

    def test_minimal_spec_mapping(self) -> None:
        """Test minimal spec mapping."""
        spec = InstanceSpec(name="test", image="ami-123")
        config = spec.to_provider_config(ProviderType.AWS)

        assert config["ami"] == "ami-123"
        assert config["instance_type"] == "t3.micro"
        assert config["associate_public_ip_address"] is False

    def test_full_spec_mapping(self) -> None:
        """Test full spec mapping."""
        spec = InstanceSpec(
            name="web-server",
            cpu_cores=4,
            memory_gb=8,
            disk_gb=100,
            image="ami-ubuntu",
            subnet="subnet-456",
            security_groups=["sg-789"],
            public_ip=True,
            ssh_key_name="my-key",
            user_data="#!/bin/bash\necho test",
            tags={"env": "prod"},
        )
        config = spec.to_provider_config(ProviderType.AWS)

        assert config["ami"] == "ami-ubuntu"
        assert config["instance_type"] == "t3.large"  # 4 CPU, 8GB
        assert config["subnet_id"] == "subnet-456"
        assert config["vpc_security_group_ids"] == ["sg-789"]
        assert config["associate_public_ip_address"] is True
        assert config["key_name"] == "my-key"
        assert config["user_data"] == "#!/bin/bash\necho test"
        assert config["root_block_device"]["volume_size"] == 100
