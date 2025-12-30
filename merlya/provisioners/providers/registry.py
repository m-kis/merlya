"""
Merlya Provisioners - Cloud Provider Registry.

Singleton registry for managing cloud provider implementations.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.provisioners.providers.base import (
    AbstractCloudProvider,
    ProviderCapabilities,
    ProviderType,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class CloudProviderRegistry:
    """
    Registry for cloud provider implementations.

    Manages provider registration and instantiation.
    Follows the singleton pattern with reset_instance() for tests.
    """

    _instance: CloudProviderRegistry | None = None

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: dict[ProviderType, type[AbstractCloudProvider]] = {}
        self._capabilities: dict[ProviderType, ProviderCapabilities] = {}
        self._ctx: SharedContext | None = None

    @classmethod
    def get_instance(cls) -> CloudProviderRegistry:
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for tests."""
        cls._instance = None

    def set_context(self, ctx: SharedContext) -> None:
        """
        Set the shared context for provider instantiation.

        Args:
            ctx: Shared context to use for providers.
        """
        self._ctx = ctx
        logger.debug("Cloud provider registry context updated")

    def register(
        self,
        provider_type: ProviderType,
        provider_class: type[AbstractCloudProvider],
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        """
        Register a cloud provider implementation.

        Args:
            provider_type: The provider type to register.
            provider_class: The provider class to register.
            capabilities: Optional capabilities override.
        """
        self._providers[provider_type] = provider_class
        if capabilities:
            self._capabilities[provider_type] = capabilities

        logger.debug(f"Registered cloud provider: {provider_type.value}")

    def get(self, provider_type: ProviderType) -> AbstractCloudProvider:
        """
        Get a provider instance.

        Args:
            provider_type: The provider type.

        Returns:
            Configured provider instance.

        Raises:
            ValueError: If provider not registered.
            RuntimeError: If context not set.
        """
        if self._ctx is None:
            raise RuntimeError("Context not set. Call set_context() first.")

        if provider_type not in self._providers:
            available = self.list_providers()
            raise ValueError(
                f"Provider {provider_type.value} not registered. "
                f"Available: {[p.value for p in available]}"
            )

        provider_class = self._providers[provider_type]
        return provider_class(self._ctx)

    def get_by_name(self, name: str) -> AbstractCloudProvider:
        """
        Get a provider by string name.

        Args:
            name: Provider name (e.g., "aws", "gcp").

        Returns:
            Configured provider instance.
        """
        try:
            provider_type = ProviderType(name.lower())
        except ValueError:
            available = [p.value for p in self.list_providers()]
            raise ValueError(f"Unknown provider: {name}. Available: {available}") from None

        return self.get(provider_type)

    def list_providers(self) -> list[ProviderType]:
        """List all registered provider types."""
        return list(self._providers.keys())

    def is_registered(self, provider_type: ProviderType) -> bool:
        """Check if a provider is registered."""
        return provider_type in self._providers

    def get_capabilities(self, provider_type: ProviderType) -> ProviderCapabilities:
        """
        Get capabilities for a provider.

        Returns cached capabilities or instantiates provider to get them.
        """
        if provider_type in self._capabilities:
            return self._capabilities[provider_type]

        if provider_type in self._providers and self._ctx:
            provider = self.get(provider_type)
            caps = provider.capabilities
            self._capabilities[provider_type] = caps
            return caps

        # Return default capabilities
        return ProviderCapabilities()

    def find_providers_with_capability(
        self, capability: str, value: bool = True
    ) -> list[ProviderType]:
        """
        Find providers that have a specific capability.

        Args:
            capability: Capability name (e.g., "has_mcp_support").
            value: Expected value.

        Returns:
            List of provider types with the capability.
        """
        result = []
        for provider_type in self._providers:
            caps = self.get_capabilities(provider_type)
            if hasattr(caps, capability) and getattr(caps, capability) == value:
                result.append(provider_type)
        return result


def get_cloud_provider_registry() -> CloudProviderRegistry:
    """Get the cloud provider registry singleton."""
    return CloudProviderRegistry.get_instance()
