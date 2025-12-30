"""
Tests for cloud provider registry.

v0.9.0: Initial tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from merlya.provisioners.providers.base import (
    AbstractCloudProvider,
    Instance,
    InstanceSpec,
    InstanceStatus,
    ProviderCapabilities,
    ProviderType,
)
from merlya.provisioners.providers.registry import (
    CloudProviderRegistry,
    get_cloud_provider_registry,
)


class MockProvider(AbstractCloudProvider):
    """Mock provider for testing."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.AWS

    @property
    def name(self) -> str:
        return "Mock AWS"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(has_mcp_support=True)

    async def validate_credentials(self) -> tuple[bool, str | None]:
        return True, None

    async def list_instances(self, filters: dict[str, Any] | None = None) -> list[Instance]:
        return []

    async def get_instance(self, instance_id: str) -> Instance | None:
        return None

    async def create_instance(self, spec: InstanceSpec) -> Instance:
        return Instance(id="mock-id", name=spec.name, provider=ProviderType.AWS)

    async def update_instance(self, instance_id: str, updates: dict[str, Any]) -> Instance:
        return Instance(id=instance_id, name="updated", provider=ProviderType.AWS)

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


class MockGCPProvider(MockProvider):
    """Mock GCP provider."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GCP

    @property
    def name(self) -> str:
        return "Mock GCP"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(has_mcp_support=False, supports_auto_scaling=False)


class TestCloudProviderRegistry:
    """Test CloudProviderRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self) -> None:
        """Reset singleton before each test."""
        CloudProviderRegistry.reset_instance()

    def test_singleton(self) -> None:
        """Test singleton pattern."""
        registry1 = get_cloud_provider_registry()
        registry2 = get_cloud_provider_registry()
        assert registry1 is registry2

    def test_reset_instance(self) -> None:
        """Test singleton reset."""
        registry1 = get_cloud_provider_registry()
        CloudProviderRegistry.reset_instance()
        registry2 = get_cloud_provider_registry()
        assert registry1 is not registry2

    def test_register_provider(self) -> None:
        """Test provider registration."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        assert registry.is_registered(ProviderType.AWS)
        assert ProviderType.AWS in registry.list_providers()

    def test_register_multiple_providers(self) -> None:
        """Test registering multiple providers."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)
        registry.register(ProviderType.GCP, MockGCPProvider)

        providers = registry.list_providers()
        assert ProviderType.AWS in providers
        assert ProviderType.GCP in providers

    def test_get_provider_without_context(self) -> None:
        """Test getting provider without context raises error."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        with pytest.raises(RuntimeError, match="Context not set"):
            registry.get(ProviderType.AWS)

    def test_get_provider_with_context(self) -> None:
        """Test getting provider with context."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        ctx = MagicMock()
        registry.set_context(ctx)

        provider = registry.get(ProviderType.AWS)
        assert isinstance(provider, MockProvider)
        assert provider.provider_type == ProviderType.AWS

    def test_get_unregistered_provider(self) -> None:
        """Test getting unregistered provider raises error."""
        registry = get_cloud_provider_registry()
        ctx = MagicMock()
        registry.set_context(ctx)

        with pytest.raises(ValueError, match="not registered"):
            registry.get(ProviderType.AZURE)

    def test_get_by_name(self) -> None:
        """Test getting provider by string name."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        ctx = MagicMock()
        registry.set_context(ctx)

        provider = registry.get_by_name("aws")
        assert isinstance(provider, MockProvider)

    def test_get_by_name_case_insensitive(self) -> None:
        """Test provider name lookup is case-insensitive."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        ctx = MagicMock()
        registry.set_context(ctx)

        provider = registry.get_by_name("AWS")
        assert isinstance(provider, MockProvider)

    def test_get_by_name_unknown(self) -> None:
        """Test getting unknown provider by name."""
        registry = get_cloud_provider_registry()
        ctx = MagicMock()
        registry.set_context(ctx)

        with pytest.raises(ValueError, match="Unknown provider"):
            registry.get_by_name("unknown-cloud")

    def test_is_registered(self) -> None:
        """Test is_registered check."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        assert registry.is_registered(ProviderType.AWS) is True
        assert registry.is_registered(ProviderType.GCP) is False

    def test_get_capabilities(self) -> None:
        """Test getting provider capabilities."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)

        ctx = MagicMock()
        registry.set_context(ctx)

        caps = registry.get_capabilities(ProviderType.AWS)
        assert caps.has_mcp_support is True

    def test_get_capabilities_cached(self) -> None:
        """Test capabilities are cached."""
        registry = get_cloud_provider_registry()
        custom_caps = ProviderCapabilities(can_delete=False)
        registry.register(ProviderType.AWS, MockProvider, capabilities=custom_caps)

        caps = registry.get_capabilities(ProviderType.AWS)
        assert caps.can_delete is False  # Uses cached value

    def test_find_providers_with_capability(self) -> None:
        """Test finding providers by capability."""
        registry = get_cloud_provider_registry()
        registry.register(ProviderType.AWS, MockProvider)
        registry.register(ProviderType.GCP, MockGCPProvider)

        ctx = MagicMock()
        registry.set_context(ctx)

        # Find providers with MCP support
        mcp_providers = registry.find_providers_with_capability("has_mcp_support", True)
        assert ProviderType.AWS in mcp_providers
        assert ProviderType.GCP not in mcp_providers

        # Find providers without auto-scaling
        no_autoscale = registry.find_providers_with_capability("supports_auto_scaling", False)
        assert ProviderType.GCP in no_autoscale

    def test_list_providers_empty(self) -> None:
        """Test list_providers when empty."""
        registry = get_cloud_provider_registry()
        assert registry.list_providers() == []
