"""
Tests for AgentRegistry (OCP pattern).
"""
import pytest

from athena_ai.core.registry import AgentRegistry, get_registry


class MockAgent:
    """Mock agent for testing."""
    def __init__(self, context_manager=None):
        self.context_manager = context_manager
        self.name = "MockAgent"

    def run(self, task, target="local", confirm=False, dry_run=False):
        return {"success": True, "task": task, "target": target}


class AnotherMockAgent:
    """Another mock agent."""
    def __init__(self, context_manager=None):
        self.context_manager = context_manager
        self.name = "AnotherMockAgent"

    def run(self, task, **kwargs):
        return {"success": True, "task": task}


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        AgentRegistry.reset_instance()
        yield
        AgentRegistry.reset_instance()

    def test_singleton_pattern(self):
        """Registry should be a singleton."""
        registry1 = AgentRegistry()
        registry2 = AgentRegistry()
        assert registry1 is registry2

    def test_register_agent(self):
        """Should register an agent."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)

        assert registry.has("MockAgent")
        assert "MockAgent" in registry.list_all()

    def test_get_agent(self):
        """Should instantiate and return agent."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)

        agent = registry.get("MockAgent")

        assert isinstance(agent, MockAgent)
        assert agent.name == "MockAgent"

    def test_get_agent_with_kwargs(self):
        """Should pass kwargs to agent constructor."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)

        mock_ctx = {"test": "context"}
        agent = registry.get("MockAgent", context_manager=mock_ctx)

        assert agent.context_manager == mock_ctx

    def test_get_unknown_agent_raises(self):
        """Should raise AgentError for unknown agent."""
        from athena_ai.core.exceptions import AgentError

        registry = AgentRegistry()

        with pytest.raises(AgentError) as exc_info:
            registry.get("UnknownAgent")

        assert "UnknownAgent" in str(exc_info.value)

    def test_list_all_agents(self):
        """Should list all registered agents."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)
        registry.register("AnotherMockAgent", AnotherMockAgent)

        agents = registry.list_all()

        assert "MockAgent" in agents
        assert "AnotherMockAgent" in agents
        assert len(agents) == 2

    def test_list_with_descriptions(self):
        """Should list agents with descriptions."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)

        descriptions = registry.list_with_descriptions()

        assert "MockAgent" in descriptions
        assert "Mock agent for testing" in descriptions["MockAgent"]

    def test_decorator_registration(self):
        """Should register via decorator."""
        registry = AgentRegistry()

        @registry.agent("DecoratedAgent")
        class DecoratedAgent:
            """Decorated agent."""
            pass

        assert registry.has("DecoratedAgent")

    def test_clear_registry(self):
        """Should clear all registered agents."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)

        registry.clear()

        assert len(registry.list_all()) == 0

    def test_custom_factory(self):
        """Should use custom factory for instantiation."""
        registry = AgentRegistry()

        def custom_factory(**kwargs):
            agent = MockAgent()
            agent.name = "CustomFactoryAgent"
            return agent

        registry.register("MockAgent", MockAgent, factory=custom_factory)
        agent = registry.get("MockAgent")

        assert agent.name == "CustomFactoryAgent"


class TestGetRegistry:
    """Tests for get_registry helper."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        AgentRegistry.reset_instance()
        yield
        AgentRegistry.reset_instance()

    def test_get_registry_returns_singleton(self):
        """get_registry should return the same instance."""
        registry1 = get_registry()
        registry2 = get_registry()
        assert registry1 is registry2


class TestAgentExecution:
    """Integration tests for agent execution via registry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before each test."""
        AgentRegistry.reset_instance()
        yield
        AgentRegistry.reset_instance()

    def test_execute_agent_task(self):
        """Should execute agent task through registry."""
        registry = AgentRegistry()
        registry.register("MockAgent", MockAgent)

        agent = registry.get("MockAgent")
        result = agent.run("test task", target="test-host")

        assert result["success"] is True
        assert result["task"] == "test task"
        assert result["target"] == "test-host"
