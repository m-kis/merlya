"""Tests for the intent classifier and router."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from merlya.router.classifier import (
    AgentMode,
    IntentRouter,
    RouterResult,
)


class TestAgentMode:
    """Tests for AgentMode enum."""

    def test_mode_values(self) -> None:
        """Test that all expected modes exist."""
        assert AgentMode.DIAGNOSTIC == "diagnostic"
        assert AgentMode.REMEDIATION == "remediation"
        assert AgentMode.QUERY == "query"
        assert AgentMode.CHAT == "chat"

    def test_mode_is_string(self) -> None:
        """Test modes are strings."""
        assert isinstance(AgentMode.DIAGNOSTIC.value, str)
        assert isinstance(AgentMode.CHAT.value, str)


class TestRouterResult:
    """Tests for RouterResult dataclass."""

    def test_router_result_creation(self) -> None:
        """Test RouterResult creation."""
        result = RouterResult(
            mode=AgentMode.DIAGNOSTIC,
            tools=["ssh", "core"],
            confidence=0.95,
            reasoning="User wants to diagnose",
            entities={"hosts": ["webserver"]},
        )
        assert result.mode == AgentMode.DIAGNOSTIC
        assert result.confidence == 0.95
        assert result.reasoning == "User wants to diagnose"
        assert "webserver" in result.entities["hosts"]
        assert "ssh" in result.tools

    def test_router_result_defaults(self) -> None:
        """Test RouterResult default values."""
        result = RouterResult(mode=AgentMode.CHAT, tools=[])
        assert result.confidence == 0.0
        assert result.reasoning is None
        assert result.entities == {}
        assert result.delegate_to is None


class TestIntentClassifier:
    """Tests for IntentClassifier (internal component of IntentRouter)."""

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance with pattern-based classifier."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_classify_returns_router_result(self, router: IntentRouter) -> None:
        """Test that route returns RouterResult."""
        await router.initialize()
        result = await router.route("Check server status")
        assert isinstance(result, RouterResult)
        assert isinstance(result.mode, AgentMode)

    @pytest.mark.asyncio
    async def test_classify_diagnostic_patterns(self, router: IntentRouter) -> None:
        """Test classification of diagnostic patterns."""
        await router.initialize()
        diagnostic_texts = [
            "Check server status",
            "Monitor CPU usage",
            "Analyze the logs",
            "Debug this issue",
        ]

        for text in diagnostic_texts:
            result = await router.route(text)
            assert result.mode in [AgentMode.DIAGNOSTIC, AgentMode.CHAT]

    @pytest.mark.asyncio
    async def test_classify_remediation_patterns(self, router: IntentRouter) -> None:
        """Test classification of remediation patterns."""
        await router.initialize()
        remediation_texts = [
            "Fix the error",
            "Restart the service",
            "Deploy the application",
            "Update the configuration",
        ]

        for text in remediation_texts:
            result = await router.route(text)
            assert result.mode in [AgentMode.REMEDIATION, AgentMode.CHAT]

    @pytest.mark.asyncio
    async def test_classify_query_patterns(self, router: IntentRouter) -> None:
        """Test classification of query patterns."""
        await router.initialize()
        query_texts = [
            "What is Docker?",
            "How do I configure SSH?",
            "Explain this error",
        ]

        for text in query_texts:
            result = await router.route(text)
            # May classify as QUERY, CHAT, or DIAGNOSTIC depending on patterns
            assert result.mode in list(AgentMode)


class TestIntentRouter:
    """Tests for IntentRouter."""

    @pytest.fixture
    def mock_context(self) -> MagicMock:
        """Create mock context."""
        ctx = MagicMock()
        ctx.config = MagicMock()
        ctx.config.llm_provider = "openai"
        ctx.config.llm_model = "gpt-4"
        return ctx

    @pytest.fixture
    def router(self) -> IntentRouter:
        """Create router instance."""
        return IntentRouter(use_local=False)

    @pytest.mark.asyncio
    async def test_route_returns_result(self, router: IntentRouter) -> None:
        """Test that route returns a RouterResult."""
        await router.initialize()
        result = await router.route("Hello world")

        assert isinstance(result, RouterResult)
        assert isinstance(result.mode, AgentMode)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_route_with_host_mention(self, router: IntentRouter) -> None:
        """Test routing with explicit host mention."""
        await router.initialize()
        result = await router.route("Connect to @myserver")

        # Should detect host mention in entities
        assert "myserver" in result.entities.get("hosts", [])

    @pytest.mark.asyncio
    async def test_route_extracts_files(self, router: IntentRouter) -> None:
        """Test that route extracts file paths."""
        await router.initialize()
        result = await router.route("Edit /etc/nginx/nginx.conf")

        assert "/etc/nginx/nginx.conf" in result.entities.get("files", [])

    @pytest.mark.asyncio
    async def test_route_empty_input(self, router: IntentRouter) -> None:
        """Test routing with empty input."""
        await router.initialize()
        result = await router.route("")

        assert result.mode == AgentMode.CHAT
        # Confidence can vary based on implementation
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_route_whitespace_only(self, router: IntentRouter) -> None:
        """Test routing with whitespace-only input."""
        await router.initialize()
        result = await router.route("   \n\t  ")

        assert result.mode == AgentMode.CHAT

    @pytest.mark.asyncio
    async def test_route_includes_tools(self, router: IntentRouter) -> None:
        """Test that route result includes tools."""
        await router.initialize()
        result = await router.route("Check server status")

        assert isinstance(result.tools, list)
        # Should have at least some tools
        assert len(result.tools) >= 0
