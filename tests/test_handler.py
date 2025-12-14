"""Tests for the router handler module (Sprint 7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.router.classifier import AgentMode, RouterResult
from merlya.router.handler import (
    HandlerResponse,
    handle_agent,
    handle_fast_path,
    handle_skill_flow,
    handle_user_message,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@dataclass
class MockHost:
    """Mock host for testing."""

    name: str
    hostname: str
    port: int = 22
    username: str = "admin"
    health_status: str = "healthy"
    tags: list[str] | None = None
    os_info: str | None = None
    last_seen: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []

    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "health_status": self.health_status,
            "tags": self.tags,
        }


@dataclass
class MockVariable:
    """Mock variable for testing."""

    name: str
    value: str


@pytest.fixture
def mock_context() -> MagicMock:
    """Create mock context with repositories."""
    ctx = MagicMock()
    ctx.t = MagicMock(side_effect=lambda key, **_kwargs: key)

    # Mock hosts repository
    ctx.hosts = AsyncMock()
    ctx.hosts.get_all = AsyncMock(
        return_value=[
            MockHost(
                name="web-01", hostname="10.0.0.1", health_status="healthy", tags=["web", "prod"]
            ),
            MockHost(
                name="web-02", hostname="10.0.0.2", health_status="healthy", tags=["web", "prod"]
            ),
            MockHost(
                name="db-01", hostname="10.0.0.10", health_status="healthy", tags=["db", "prod"]
            ),
            MockHost(name="backup", hostname="10.0.0.100", health_status="unreachable"),
        ]
    )

    # Mock variables repository
    ctx.variables = AsyncMock()
    ctx.variables.get_all = AsyncMock(
        return_value=[
            MockVariable(name="ENV", value="production"),
            MockVariable(name="API_URL", value="https://api.example.com"),
        ]
    )
    ctx.variables.get = AsyncMock(
        side_effect=lambda name: MockVariable(name=name, value="test_value")
        if name == "ENV"
        else None
    )

    # Mock UI
    ctx.ui = MagicMock()
    ctx.ui.prompt = AsyncMock(return_value="")

    return ctx


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create mock agent."""
    agent = MagicMock()
    response = MagicMock()
    response.message = "Agent response"
    response.actions_taken = ["action1"]
    response.suggestions = ["suggestion1"]
    agent.run = AsyncMock(return_value=response)
    return agent


# ==============================================================================
# HandlerResponse Tests
# ==============================================================================


class TestHandlerResponse:
    """Tests for HandlerResponse dataclass."""

    def test_creation(self) -> None:
        """Test HandlerResponse creation."""
        response = HandlerResponse(
            message="Test message",
            actions_taken=["action1"],
            suggestions=["suggestion1"],
            handled_by="test",
        )
        assert response.message == "Test message"
        assert response.actions_taken == ["action1"]
        assert response.suggestions == ["suggestion1"]
        assert response.handled_by == "test"

    def test_defaults(self) -> None:
        """Test HandlerResponse default values."""
        response = HandlerResponse(message="Test")
        assert response.actions_taken is None
        assert response.suggestions is None
        assert response.handled_by == "unknown"
        assert response.raw_data is None

    def test_from_agent_response(self) -> None:
        """Test creation from AgentResponse."""
        agent_response = MagicMock()
        agent_response.message = "Agent message"
        agent_response.actions_taken = ["ssh_execute"]
        agent_response.suggestions = ["Check logs"]

        response = HandlerResponse.from_agent_response(agent_response)

        assert response.message == "Agent message"
        assert response.actions_taken == ["ssh_execute"]
        assert response.suggestions == ["Check logs"]
        assert response.handled_by == "agent"


# ==============================================================================
# Fast Path Tests
# ==============================================================================


class TestHandleFastPath:
    """Tests for handle_fast_path function."""

    @pytest.mark.asyncio
    async def test_host_list(self, mock_context: MagicMock) -> None:
        """Test host.list fast path."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
            fast_path_args={},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert response.handled_by == "fast_path"
        assert "Host Inventory" in response.message
        assert "web-01" in response.message
        assert "Total: 4 hosts" in response.message

    @pytest.mark.asyncio
    async def test_host_list_empty(self, mock_context: MagicMock) -> None:
        """Test host.list with empty inventory."""
        mock_context.hosts.get_all = AsyncMock(return_value=[])

        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
            fast_path_args={},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert "No hosts in inventory" in response.message
        assert "/scan" in response.suggestions

    @pytest.mark.asyncio
    async def test_host_details_found(self, mock_context: MagicMock) -> None:
        """Test host.details for existing host."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.details",
            fast_path_args={"target": "web-01"},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert response.handled_by == "fast_path"
        assert "Host: @web-01" in response.message
        assert "10.0.0.1" in response.message

    @pytest.mark.asyncio
    async def test_host_details_not_found(self, mock_context: MagicMock) -> None:
        """Test host.details for non-existent host."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.details",
            fast_path_args={"target": "nonexistent"},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert "not found" in response.message

    @pytest.mark.asyncio
    async def test_group_list(self, mock_context: MagicMock) -> None:
        """Test group.list fast path."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="group.list",
            fast_path_args={},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert response.handled_by == "fast_path"
        assert "Host Groups" in response.message
        assert "web" in response.message or "prod" in response.message

    @pytest.mark.asyncio
    async def test_var_list(self, mock_context: MagicMock) -> None:
        """Test var.list fast path."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="var.list",
            fast_path_args={},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert response.handled_by == "fast_path"
        assert "Variables" in response.message
        assert "ENV" in response.message

    @pytest.mark.asyncio
    async def test_var_get_found(self, mock_context: MagicMock) -> None:
        """Test var.get for existing variable."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="var.get",
            fast_path_args={"target": "ENV"},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert response.handled_by == "fast_path"
        assert "ENV" in response.message
        assert "test_value" in response.message

    @pytest.mark.asyncio
    async def test_var_get_not_found(self, mock_context: MagicMock) -> None:
        """Test var.get for non-existent variable."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="var.get",
            fast_path_args={"target": "NONEXISTENT"},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert "not found" in response.message

    @pytest.mark.asyncio
    async def test_unknown_fast_path(self, mock_context: MagicMock) -> None:
        """Test unknown fast path intent."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="unknown.intent",
            fast_path_args={},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert "Unknown fast path intent" in response.message


# ==============================================================================
# Skill Flow Tests
# ==============================================================================


class TestHandleSkillFlow:
    """Tests for handle_skill_flow function."""

    @pytest.mark.asyncio
    async def test_skill_not_found(self, mock_context: MagicMock) -> None:
        """Test skill flow when skill not found."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="nonexistent_skill",
            skill_confidence=0.8,
        )

        with patch("merlya.skills.registry.get_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get.return_value = None
            mock_get_registry.return_value = mock_registry

            response = await handle_skill_flow(mock_context, "test input", route_result)

        assert response is None

    @pytest.mark.asyncio
    async def test_skill_needs_hosts(self, mock_context: MagicMock) -> None:
        """Test skill flow when hosts are required but not provided."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_audit",
            skill_confidence=0.8,
            entities={"hosts": []},
        )

        mock_skill = MagicMock()
        mock_skill.name = "disk_audit"
        mock_skill.description = "Check disk usage"
        mock_skill.max_hosts = 5

        with patch("merlya.skills.registry.get_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get.return_value = mock_skill
            mock_get_registry.return_value = mock_registry

            response = await handle_skill_flow(mock_context, "check disk", route_result)

        assert response is not None
        assert "specify target hosts" in response.message


# ==============================================================================
# Handle Agent Tests
# ==============================================================================


class TestHandleAgent:
    """Tests for handle_agent function."""

    @pytest.mark.asyncio
    async def test_agent_response(self, mock_context: MagicMock, mock_agent: MagicMock) -> None:
        """Test agent handler returns proper response."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core", "system"],
        )

        response = await handle_agent(mock_context, mock_agent, "test input", route_result)

        assert response.handled_by == "agent"
        assert response.message == "Agent response"
        mock_agent.run.assert_called_once_with("test input", route_result)


# ==============================================================================
# Handle User Message Integration Tests
# ==============================================================================


class TestHandleUserMessage:
    """Tests for handle_user_message main entry point."""

    @pytest.mark.asyncio
    async def test_fast_path_routing(self, mock_context: MagicMock, mock_agent: MagicMock) -> None:
        """Test that fast path is used when detected."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
            fast_path_args={},
        )

        response = await handle_user_message(mock_context, mock_agent, "list hosts", route_result)

        assert response.handled_by == "fast_path"
        # Agent should NOT be called for fast path
        mock_agent.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_fallback(self, mock_context: MagicMock, mock_agent: MagicMock) -> None:
        """Test agent fallback when no fast path or skill match."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            # No fast_path, no skill_match
        )

        response = await handle_user_message(
            mock_context, mock_agent, "check server status", route_result
        )

        assert response.handled_by == "agent"
        mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompts_for_target_on_ambiguous_ops(self, mock_context: MagicMock) -> None:
        """If no host is specified for an execution request, prompt for local vs inventory host."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core", "system"],
            entities={"hosts": [], "variables": [], "files": []},
        )

        mock_context.ui.prompt = AsyncMock(return_value="WEB-01")
        mock_context.hosts.get_by_name = AsyncMock(
            return_value=MockHost(name="web-01", hostname="10.0.0.1")
        )

        agent = MagicMock()
        response = MagicMock()
        response.message = "Agent response"
        response.actions_taken = []
        response.suggestions = []
        agent.run = AsyncMock(return_value=response)

        out = await handle_user_message(mock_context, agent, "donne moi des infos sur PID 123", route_result)

        assert out.handled_by == "agent"
        agent.run.assert_called_once()
        called_input = agent.run.await_args.args[0]
        assert "On @web-01:" in called_input

    @pytest.mark.asyncio
    async def test_prompts_for_target_local(self, mock_context: MagicMock) -> None:
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core", "system"],
            entities={"hosts": [], "variables": [], "files": []},
        )

        mock_context.ui.prompt = AsyncMock(return_value="local")

        agent = MagicMock()
        response = MagicMock()
        response.message = "Agent response"
        response.actions_taken = []
        response.suggestions = []
        agent.run = AsyncMock(return_value=response)

        out = await handle_user_message(mock_context, agent, "info PID 123", route_result)

        assert out.handled_by == "agent"
        called_input = agent.run.await_args.args[0]
        assert "LOCAL EXECUTION CONTEXT" in called_input

    @pytest.mark.asyncio
    async def test_skill_routing_with_high_confidence(
        self, mock_context: MagicMock, mock_agent: MagicMock
    ) -> None:
        """Test skill routing when confidence is high."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_audit",
            skill_confidence=0.9,  # Above threshold
            entities={"hosts": []},
        )

        mock_skill = MagicMock()
        mock_skill.name = "disk_audit"
        mock_skill.description = "Check disk usage"
        mock_skill.max_hosts = 5

        with patch("merlya.skills.registry.get_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.get.return_value = mock_skill
            mock_get_registry.return_value = mock_registry

            response = await handle_user_message(
                mock_context, mock_agent, "check disk", route_result
            )

        # Should use skill handler (asks for hosts)
        assert response.handled_by == "skill"

    @pytest.mark.asyncio
    async def test_skill_routing_low_confidence_falls_to_agent(
        self, mock_context: MagicMock, mock_agent: MagicMock
    ) -> None:
        """Test that low confidence skill match falls back to agent."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_audit",
            skill_confidence=0.4,  # Below threshold
        )

        response = await handle_user_message(
            mock_context, mock_agent, "maybe check disk", route_result
        )

        # Should fall back to agent due to low confidence
        assert response.handled_by == "agent"
        mock_agent.run.assert_called_once()


# ==============================================================================
# RouterResult Fast Path Properties Tests
# ==============================================================================


class TestRouterResultFastPathProperties:
    """Tests for RouterResult fast path properties."""

    def test_is_fast_path_true(self) -> None:
        """Test is_fast_path returns True when fast_path is set."""
        result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
        )
        assert result.is_fast_path is True

    def test_is_fast_path_false(self) -> None:
        """Test is_fast_path returns False when fast_path is None."""
        result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
        )
        assert result.is_fast_path is False

    def test_is_skill_match_true(self) -> None:
        """Test is_skill_match returns True with high confidence."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_audit",
            skill_confidence=0.8,
        )
        assert result.is_skill_match is True

    def test_is_skill_match_low_confidence(self) -> None:
        """Test is_skill_match returns False with low confidence."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="disk_audit",
            skill_confidence=0.3,
        )
        assert result.is_skill_match is False

    def test_is_skill_match_no_skill(self) -> None:
        """Test is_skill_match returns False when no skill matched."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
        )
        assert result.is_skill_match is False


# ==============================================================================
# Fast Path Detection Tests (via classifier)
# ==============================================================================


class TestFastPathDetection:
    """Tests for fast path detection in IntentRouter."""

    @pytest.fixture
    def router(self) -> Any:
        """Create router instance."""
        from merlya.router.classifier import IntentRouter

        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_detect_host_list_english(self, router: Any) -> None:
        """Test detection of 'list hosts' pattern."""
        await router.initialize()
        result = await router.route("list hosts")

        assert result.is_fast_path
        assert result.fast_path == "host.list"

    @pytest.mark.asyncio
    async def test_detect_host_list_french(self, router: Any) -> None:
        """Test detection of 'liste les machines' pattern (French)."""
        await router.initialize()
        result = await router.route("liste les machines")

        assert result.is_fast_path
        assert result.fast_path == "host.list"

    @pytest.mark.asyncio
    async def test_detect_show_hosts(self, router: Any) -> None:
        """Test detection of 'show hosts' pattern."""
        await router.initialize()
        result = await router.route("show hosts")

        assert result.is_fast_path
        assert result.fast_path == "host.list"

    @pytest.mark.asyncio
    async def test_detect_inventory(self, router: Any) -> None:
        """Test detection of 'inventory' keyword."""
        await router.initialize()
        result = await router.route("inventory")

        assert result.is_fast_path
        assert result.fast_path == "host.list"

    @pytest.mark.asyncio
    async def test_detect_host_details(self, router: Any) -> None:
        """Test detection of host details pattern."""
        await router.initialize()
        result = await router.route("info on @web-01")

        assert result.is_fast_path
        assert result.fast_path == "host.details"
        assert result.fast_path_args.get("target") == "web-01"

    @pytest.mark.asyncio
    async def test_detect_single_host_mention(self, router: Any) -> None:
        """Test detection of single @hostname."""
        await router.initialize()
        result = await router.route("@web-01")

        assert result.is_fast_path
        assert result.fast_path == "host.details"
        assert result.fast_path_args.get("target") == "web-01"

    @pytest.mark.asyncio
    async def test_detect_group_list(self, router: Any) -> None:
        """Test detection of group list pattern."""
        await router.initialize()
        result = await router.route("list groups")

        assert result.is_fast_path
        assert result.fast_path == "group.list"

    @pytest.mark.asyncio
    async def test_detect_skill_list(self, router: Any) -> None:
        """Test detection of skill list pattern."""
        await router.initialize()
        result = await router.route("list skills")

        assert result.is_fast_path
        assert result.fast_path == "skill.list"

    @pytest.mark.asyncio
    async def test_no_fast_path_for_complex_query(self, router: Any) -> None:
        """Test that complex queries don't trigger fast path."""
        await router.initialize()
        result = await router.route("Check disk usage on all web servers and report issues")

        assert not result.is_fast_path

    @pytest.mark.asyncio
    async def test_no_fast_path_for_diagnostic(self, router: Any) -> None:
        """Test that diagnostic queries don't trigger fast path."""
        await router.initialize()
        result = await router.route("Analyze the logs for errors")

        assert not result.is_fast_path
