"""
Agent Registry - Dynamic agent registration (OCP).

Replaces hard-coded if/elif chains with a registry pattern.
Adding new agents requires only registration, not code modification.
"""
from typing import Any, Callable, Dict, Optional, Type, TypeVar

from merlya.core.exceptions import AgentError
from merlya.utils.logger import logger

T = TypeVar("T")


class AgentRegistry:
    """
    Registry for dynamic agent registration and lookup.

    Implements the Registry pattern following OCP (Open/Closed Principle):
    - Open for extension (register new agents anytime)
    - Closed for modification (no code changes needed)

    Usage:
        registry = AgentRegistry()

        # Register agents
        registry.register("DiagnosticAgent", DiagnosticAgent)
        registry.register("RemediationAgent", RemediationAgent)

        # Or use decorator
        @registry.agent("CloudAgent")
        class CloudAgent(BaseAgent):
            ...

        # Dispatch dynamically
        agent = registry.get("DiagnosticAgent", context_manager=ctx)
        result = agent.run(task, target=target)
    """

    _instance: Optional["AgentRegistry"] = None
    _agents: Dict[str, Type[Any]]
    _factories: Dict[str, Callable[..., Any]]

    def __new__(cls) -> "AgentRegistry":
        """Singleton pattern for global registry access."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
            cls._instance._factories = {}
        return cls._instance

    def register(
        self,
        name: str,
        agent_class: Type,
        factory: Optional[Callable[..., Any]] = None
    ) -> None:
        """
        Register an agent class by name.

        Args:
            name: Agent name (e.g., "DiagnosticAgent")
            agent_class: The agent class to register
            factory: Optional factory function for custom instantiation
        """
        if name in self._agents:
            logger.warning(f"Agent '{name}' already registered, overwriting")

        self._agents[name] = agent_class
        if factory:
            self._factories[name] = factory

        logger.debug(f"Registered agent: {name}")

    def agent(self, name: str) -> Callable[[Type[T]], Type[T]]:
        """
        Decorator for agent registration.

        Usage:
            @registry.agent("DiagnosticAgent")
            class DiagnosticAgent(BaseAgent):
                ...
        """
        def decorator(cls: Type[T]) -> Type[T]:
            self.register(name, cls)
            return cls
        return decorator

    def get(self, name: str, **kwargs) -> Any:
        """
        Get an agent instance by name.

        Args:
            name: Agent name
            **kwargs: Arguments to pass to agent constructor

        Returns:
            Instantiated agent

        Raises:
            AgentError: If agent not found
        """
        if name not in self._agents:
            available = ", ".join(self._agents.keys())
            raise AgentError(
                f"Agent '{name}' not found. Available: {available}"
            )

        agent_class = self._agents[name]

        # Use factory if provided
        if name in self._factories:
            return self._factories[name](**kwargs)

        return agent_class(**kwargs)

    def has(self, name: str) -> bool:
        """Check if an agent is registered."""
        return name in self._agents

    def list_all(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def list_with_descriptions(self) -> Dict[str, str]:
        """
        List agents with their docstring descriptions.

        Returns:
            Dict mapping agent name to description
        """
        result = {}
        for name, cls in self._agents.items():
            doc = cls.__doc__ or "No description"
            # Take first line of docstring
            result[name] = doc.strip().split("\n")[0]
        return result

    def clear(self) -> None:
        """Clear all registered agents (useful for testing)."""
        self._agents.clear()
        self._factories.clear()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        cls._instance = None


# Global registry instance
_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def register_agent(
    name: str,
    agent_class: Type,
    factory: Optional[Callable[..., Any]] = None
) -> None:
    """Convenience function to register an agent."""
    get_registry().register(name, agent_class, factory)


def get_agent(name: str, **kwargs) -> Any:
    """Convenience function to get an agent."""
    return get_registry().get(name, **kwargs)


# =============================================================================
# Built-in Agent Registration
# =============================================================================

def register_builtin_agents() -> None:
    """
    Register all built-in Merlya agents.

    This is called once at startup to populate the registry.
    New agents only need to be added here - no changes to coordinator needed.
    """
    registry = get_registry()

    # Lazy imports to avoid circular dependencies
    from merlya.agents.cloud import CloudAgent
    from merlya.agents.diagnostic import DiagnosticAgent
    from merlya.agents.monitoring import MonitoringAgent
    from merlya.agents.provisioning import ProvisioningAgent
    from merlya.agents.remediation import RemediationAgent

    registry.register("DiagnosticAgent", DiagnosticAgent)
    registry.register("RemediationAgent", RemediationAgent)
    registry.register("MonitoringAgent", MonitoringAgent)
    registry.register("ProvisioningAgent", ProvisioningAgent)
    registry.register("CloudAgent", CloudAgent)

    logger.info(f"Registered {len(registry.list_all())} built-in agents")


__all__ = [
    "AgentRegistry",
    "get_registry",
    "register_agent",
    "get_agent",
    "register_builtin_agents",
]
