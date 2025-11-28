"""
CI Platform Registry - Dynamic platform registration (OCP).

Follows the same pattern as athena_ai/core/registry.py for agents.
Adding new platforms requires only registration, not code modification.
"""

from typing import Any, Callable, Dict, Optional, Type, TypeVar

from athena_ai.utils.logger import logger

T = TypeVar("T")


class CIPlatformRegistry:
    """
    Registry for dynamic CI platform registration and lookup.

    Implements the Registry pattern following OCP (Open/Closed Principle):
    - Open for extension (register new platforms anytime)
    - Closed for modification (no code changes needed)

    Usage:
        registry = get_ci_registry()

        # Register platforms
        registry.register("github", GitHubCIAdapter)
        registry.register("gitlab", GitLabCIAdapter)

        # Or use decorator
        @registry.platform("jenkins")
        class JenkinsCIAdapter(BaseCIAdapter):
            ...

        # Get adapter instance
        adapter = registry.get("github", config=my_config)
    """

    _instance: Optional["CIPlatformRegistry"] = None

    def __new__(cls) -> "CIPlatformRegistry":
        """Singleton pattern for global registry access."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._platforms: Dict[str, Type] = {}
            cls._instance._factories: Dict[str, Callable[..., Any]] = {}
            cls._instance._active: Dict[str, Any] = {}
        return cls._instance

    def register(
        self,
        name: str,
        adapter_class: Type[T],
        factory: Optional[Callable[..., T]] = None,
    ) -> None:
        """
        Register a CI platform adapter by name.

        Args:
            name: Platform name (e.g., "github", "gitlab")
            adapter_class: The adapter class to register
            factory: Optional factory function for custom instantiation
        """
        if name in self._platforms:
            logger.warning(f"CI Platform '{name}' already registered, overwriting")

        self._platforms[name] = adapter_class
        if factory:
            self._factories[name] = factory

        logger.debug(f"Registered CI platform: {name}")

    def platform(self, name: str) -> Callable[[Type[T]], Type[T]]:
        """
        Decorator for platform registration.

        Usage:
            @registry.platform("github")
            class GitHubCIAdapter(BaseCIAdapter):
                ...
        """

        def decorator(cls: Type[T]) -> Type[T]:
            self.register(name, cls)
            return cls

        return decorator

    def get(self, name: str, **kwargs) -> Any:
        """
        Get a CI platform adapter instance by name.

        Args:
            name: Platform name
            **kwargs: Arguments to pass to adapter constructor

        Returns:
            Instantiated adapter

        Raises:
            KeyError: If platform not found
        """
        if name not in self._platforms:
            available = ", ".join(self._platforms.keys()) or "none"
            raise KeyError(f"CI Platform '{name}' not found. Available: {available}")

        adapter_class = self._platforms[name]

        # Use factory if provided
        if name in self._factories:
            return self._factories[name](**kwargs)

        return adapter_class(**kwargs)

    def get_cached(self, name: str, cache_key: str = "", **kwargs) -> Any:
        """
        Get a cached adapter instance.

        Args:
            name: Platform name
            cache_key: Additional cache key (e.g., repo slug)
            **kwargs: Arguments for first instantiation

        Returns:
            Cached or new adapter instance
        """
        full_key = f"{name}:{cache_key}" if cache_key else name

        if full_key not in self._active:
            self._active[full_key] = self.get(name, **kwargs)

        return self._active[full_key]

    def has(self, name: str) -> bool:
        """Check if a platform is registered."""
        return name in self._platforms

    def list_all(self) -> list[str]:
        """List all registered platform names."""
        return list(self._platforms.keys())

    def list_with_descriptions(self) -> Dict[str, str]:
        """
        List platforms with their docstring descriptions.

        Returns:
            Dict mapping platform name to description
        """
        result = {}
        for name, cls in self._platforms.items():
            doc = cls.__doc__ or "No description"
            # Take first line of docstring
            result[name] = doc.strip().split("\n")[0]
        return result

    def clear_cache(self) -> None:
        """Clear cached adapter instances."""
        self._active.clear()

    def clear(self) -> None:
        """Clear all registered platforms (useful for testing)."""
        self._platforms.clear()
        self._factories.clear()
        self._active.clear()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        cls._instance = None


# Global registry instance
_registry: Optional[CIPlatformRegistry] = None


def get_ci_registry() -> CIPlatformRegistry:
    """Get the global CI platform registry."""
    global _registry
    if _registry is None:
        _registry = CIPlatformRegistry()
    return _registry


def register_builtin_platforms() -> None:
    """
    Register all built-in CI platforms.

    This is called once at startup to populate the registry.
    New platforms only need to be added here - no changes elsewhere needed.
    """
    registry = get_ci_registry()

    # Lazy imports to avoid circular dependencies
    from athena_ai.ci.adapters.github import GitHubCIAdapter

    registry.register("github", GitHubCIAdapter)

    # GitLab adapter - register when implemented
    try:
        from athena_ai.ci.adapters.gitlab import GitLabCIAdapter

        registry.register("gitlab", GitLabCIAdapter)
    except ImportError:
        logger.debug("GitLab adapter not available")

    # Jenkins adapter - register when implemented
    try:
        from athena_ai.ci.adapters.jenkins import JenkinsCIAdapter

        registry.register("jenkins", JenkinsCIAdapter)
    except ImportError:
        logger.debug("Jenkins adapter not available")

    logger.info(f"Registered {len(registry.list_all())} CI platforms")
