"""Tests for the router handler module (Sprint 7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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

    # Explicitly set _orchestrator to None so legacy agent fallback works
    ctx._orchestrator = None

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
        assert response.handled_by == "orchestrator"  # New default in simplified handler
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

    def test_from_agent_response_with_empty_lists(self) -> None:
        """Test that empty lists are preserved as lists (not converted to None) and proper message/handled_by values are set."""
        agent_response = MagicMock()
        agent_response.message = "Agent message with empty actions"
        agent_response.actions_taken = []
        agent_response.suggestions = []

        response = HandlerResponse.from_agent_response(agent_response)

        # Verify message and handled_by values
        assert response.message == "Agent message with empty actions"
        assert response.handled_by == "agent"

        # Verify that empty lists are preserved as lists, not converted to None (list preservation behavior)
        assert isinstance(response.actions_taken, list)
        assert isinstance(response.suggestions, list)
        assert response.actions_taken == []
        assert response.suggestions == []


# ==============================================================================
# Fast Path Tests (DEPRECATED - now handled by slash commands)
# ==============================================================================


class TestHandleFastPath:
    """Tests for handle_fast_path function (DEPRECATED).

    NOTE: Fast path operations are now handled by slash commands.
    handle_fast_path() returns a deprecation message directing users
    to use slash commands instead.
    """

    @pytest.mark.asyncio
    async def test_deprecated_returns_message(self, mock_context: MagicMock) -> None:
        """Test that fast path returns deprecation message."""
        route_result = RouterResult(
            mode=AgentMode.QUERY,
            tools=["core"],
            fast_path="host.list",
            fast_path_args={},
        )

        response = await handle_fast_path(mock_context, route_result)

        assert response.handled_by == "deprecated"
        # Should suggest using slash commands
        assert "/hosts" in response.suggestions or "/vars" in response.suggestions


# NOTE: Old fast path tests removed - fast path is now handled by slash commands.
# handle_fast_path() is deprecated and returns a deprecation message.


# ==============================================================================
# Skill Flow Tests (DEPRECATED - skills have been removed)
# ==============================================================================


class TestHandleSkillFlow:
    """Tests for handle_skill_flow function (DEPRECATED).

    NOTE: Skills have been removed from Merlya.
    handle_skill_flow() always returns None.
    """

    @pytest.mark.asyncio
    async def test_skill_flow_returns_none(self, mock_context: MagicMock) -> None:
        """Test skill flow always returns None (skills removed)."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
            skill_match="any_skill",
            skill_confidence=0.95,
        )

        response = await handle_skill_flow(mock_context, "test input", route_result)

        # Skills are removed, always returns None
        assert response is None


# ==============================================================================
# Handle Agent Tests (DEPRECATED - now uses Orchestrator)
# ==============================================================================


class TestHandleAgent:
    """Tests for handle_agent function (DEPRECATED).

    NOTE: handle_agent is deprecated and redirects to handle_user_message.
    The new architecture uses Orchestrator for LLM processing.
    """

    @pytest.mark.asyncio
    async def test_agent_legacy_calls_run(
        self, mock_context: MagicMock, mock_agent: MagicMock
    ) -> None:
        """Test legacy agent handler falls back to agent.run()."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core", "system"],
        )

        response = await handle_agent(mock_context, mock_agent, "test input", route_result)

        # Legacy handler calls agent.run if agent has run method
        assert response.handled_by == "agent_legacy"
        mock_agent.run.assert_called_once()


# ==============================================================================
# Handle User Message Integration Tests (DEPRECATED)
# ==============================================================================


class TestHandleUserMessage:
    """Tests for handle_user_message (DEPRECATED).

    NOTE: handle_user_message is deprecated. The new architecture is:
    - "/" commands → Slash command dispatch (fast-path)
    - Free text → Orchestrator (LLM) via handle_message()

    These tests verify the legacy fallback behavior for backward compatibility.
    """

    @pytest.mark.asyncio
    async def test_legacy_agent_fallback(
        self, mock_context: MagicMock, mock_agent: MagicMock
    ) -> None:
        """Test legacy handler falls back to agent.run()."""
        route_result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["core"],
        )

        response = await handle_user_message(
            mock_context, mock_agent, "check server status", route_result
        )

        # Legacy handler calls agent.run if agent has run method
        assert response.handled_by == "agent_legacy"
        mock_agent.run.assert_called_once()


# NOTE: Tests for skill routing, target prompts, etc. have been removed
# as they tested deprecated functionality. Skills have been removed and
# the new architecture uses Orchestrator for all LLM processing.


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
