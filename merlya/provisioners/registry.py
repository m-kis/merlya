"""
Merlya Provisioners - Registry.

Singleton registry for managing provisioner types and instances.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.provisioners.base import (
        AbstractProvisioner,
        ProvisionerAction,
        ProvisionerDeps,
    )


class ProvisionerRegistry:
    """
    Registry for infrastructure provisioners.

    Manages provisioner types and provides factory methods.
    Follows the singleton pattern with reset_instance() for tests.
    """

    _instance: ProvisionerRegistry | None = None

    def __init__(self) -> None:
        """Initialize empty registry."""
        # Map: (provider, backend) -> provisioner class
        self._provisioners: dict[tuple[str, str], type[AbstractProvisioner]] = {}
        # Map: provider -> default backend
        self._default_backends: dict[str, str] = {}
        self._ctx: SharedContext | None = None

    @classmethod
    def get_instance(cls) -> ProvisionerRegistry:
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
        Set the shared context for provisioner instantiation.

        Args:
            ctx: Shared context to use for provisioners.
        """
        self._ctx = ctx
        logger.debug("Provisioner registry context updated")

    def register(
        self,
        provider: str,
        backend: str,
        provisioner_class: type[AbstractProvisioner],
        is_default: bool = False,
    ) -> None:
        """
        Register a provisioner class.

        Args:
            provider: Cloud provider (aws, gcp, azure, etc.).
            backend: Backend type (mcp, terraform, pulumi).
            provisioner_class: The provisioner class to register.
            is_default: Whether this is the default backend for the provider.
        """
        key = (provider.lower(), backend.lower())
        self._provisioners[key] = provisioner_class

        if is_default:
            self._default_backends[provider.lower()] = backend.lower()

        logger.debug(
            f"Registered provisioner: {provider}/{backend} -> {provisioner_class.__name__}"
            f"{' (default)' if is_default else ''}"
        )

    def get(
        self,
        deps: ProvisionerDeps,
    ) -> AbstractProvisioner:
        """
        Get a provisioner instance for the given dependencies.

        Args:
            deps: Provisioner dependencies including provider and backend.

        Returns:
            Configured provisioner instance.

        Raises:
            ValueError: If no provisioner registered for provider/backend.
            RuntimeError: If context not set.
        """
        if self._ctx is None:
            raise RuntimeError("Context not set. Call set_context() first.")

        provider = deps.provider.lower()
        backend = deps.backend.lower()

        # Handle "auto" backend selection
        if backend == "auto":
            backend = self._select_best_backend(provider)
            logger.debug(f"Auto-selected backend '{backend}' for provider '{provider}'")

        key = (provider, backend)
        if key not in self._provisioners:
            available = self.list_backends(provider)
            raise ValueError(
                f"No provisioner for {provider}/{backend}. "
                f"Available backends for {provider}: {available or 'none'}"
            )

        provisioner_class = self._provisioners[key]
        return provisioner_class(self._ctx, deps)

    def _select_best_backend(self, provider: str) -> str:
        """
        Select the best available backend for a provider.

        Priority: MCP (if available) > default > first registered

        Args:
            provider: Cloud provider name.

        Returns:
            Selected backend name.
        """
        # Check if MCP is available for this provider
        mcp_key = (provider, "mcp")
        if mcp_key in self._provisioners:
            # TODO: Check if MCP server is actually running
            return "mcp"

        # Use configured default
        if provider in self._default_backends:
            return self._default_backends[provider]

        # Fall back to first registered
        for p, b in self._provisioners:
            if p == provider:
                return b

        raise ValueError(f"No provisioner registered for provider: {provider}")

    def list_providers(self) -> list[str]:
        """List all registered providers."""
        return sorted({p for p, _ in self._provisioners})

    def list_backends(self, provider: str) -> list[str]:
        """List available backends for a provider."""
        provider = provider.lower()
        return sorted([b for p, b in self._provisioners if p == provider])

    def is_registered(self, provider: str, backend: str) -> bool:
        """Check if a provisioner is registered."""
        return (provider.lower(), backend.lower()) in self._provisioners

    def get_for_action(
        self,
        action: ProvisionerAction,
        provider: str,
        resources: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AbstractProvisioner:
        """
        Convenience method to get a provisioner for an action.

        Args:
            action: The action to perform.
            provider: Cloud provider.
            resources: List of resource specifications.
            **kwargs: Additional deps parameters.

        Returns:
            Configured provisioner instance.
        """
        from merlya.provisioners.base import ProvisionerDeps, ResourceSpec

        resource_specs = [ResourceSpec(**r) if isinstance(r, dict) else r for r in resources]

        deps = ProvisionerDeps(
            action=action,
            provider=provider,
            resources=resource_specs,
            **kwargs,
        )

        return self.get(deps)


# Convenience function
def get_provisioner_registry() -> ProvisionerRegistry:
    """Get the provisioner registry singleton."""
    return ProvisionerRegistry.get_instance()
