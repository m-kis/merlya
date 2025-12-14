"""Tests for /mcp command handlers."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers import init_commands
from merlya.commands.handlers import mcp as mcp_module
from merlya.commands.handlers.mcp import _extract_add_options
from merlya.commands.registry import CommandRegistry, get_registry
from merlya.mcp.manager import MCPToolInfo


@pytest.fixture
def registry() -> CommandRegistry:
    """Initialize command registry."""
    init_commands()
    return get_registry()


@pytest.fixture
def ctx() -> MagicMock:
    """Minimal context mock with UI stubs."""
    mock = MagicMock()
    mock.ui = MagicMock()
    mock.ui.table = MagicMock()
    mock.ui.info = MagicMock()
    mock.config = MagicMock()
    return mock


@pytest.mark.asyncio
async def test_mcp_add_parses_env_and_args(
    monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock
):
    """Ensure /mcp add forwards parsed command/args/env to manager and tests connection."""
    tools = [MCPToolInfo(name="github.search", description="Search", server="github")]
    manager = SimpleNamespace(
        add_server=AsyncMock(),
        list_servers=AsyncMock(return_value=[]),
        show_server=AsyncMock(return_value=None),  # Server doesn't exist yet
        test_server=AsyncMock(return_value={"tools": tools, "tool_count": 1}),
    )
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))

    # Mock spinner context manager
    ctx.ui.spinner = MagicMock(return_value=nullcontext())

    result = await registry.execute(
        ctx,
        "/mcp add github npx -y @modelcontextprotocol/server-github --env=GITHUB_TOKEN=${GITHUB_TOKEN}",
    )

    assert result is not None and result.success
    assert "added and connected successfully" in result.message
    manager.add_server.assert_awaited_with(
        "github",
        "npx",
        ["-y", "@modelcontextprotocol/server-github"],
        {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        cwd=None,
    )
    manager.test_server.assert_awaited_once_with("github")


@pytest.mark.asyncio
async def test_mcp_tools_lists_tools(
    monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock
):
    """Ensure /mcp tools renders tool list."""
    tools = [
        MCPToolInfo(name="github.search_repos", description="Search repos", server="github"),
        MCPToolInfo(name="slack.post_message", description=None, server="slack"),
    ]
    manager = SimpleNamespace(list_tools=AsyncMock(return_value=tools))
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))

    result = await registry.execute(ctx, "/mcp tools")

    assert result is not None and result.success
    assert result.data == {"tools": [tool.name for tool in tools]}
    ctx.ui.table.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_test_reports_errors(
    monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock
):
    """Ensure /mcp test surfaces connection errors."""

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    manager = SimpleNamespace(test_server=_raise)
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))
    ctx.ui.spinner = MagicMock(return_value=nullcontext())

    result = await registry.execute(ctx, "/mcp test github")

    assert result is not None and not result.success
    assert "Failed to connect" in result.message


# --- New tests for auto-test and --no-test flag ---


class TestExtractAddOptions:
    """Tests for _extract_add_options helper."""

    def test_extracts_env_vars(self):
        """Parse --env=KEY=VALUE flags."""
        args = ["npx", "-y", "server", "--env=TOKEN=${secret}", "--env=PORT=8080"]
        env, cwd, no_test, remaining = _extract_add_options(args)

        assert env == {"TOKEN": "${secret}", "PORT": "8080"}
        assert cwd is None
        assert no_test is False
        assert remaining == ["npx", "-y", "server"]

    def test_extracts_cwd(self):
        """Parse --cwd=/path flag."""
        args = ["python", "server.py", "--cwd=/opt/mcp"]
        env, cwd, no_test, remaining = _extract_add_options(args)

        assert env == {}
        assert cwd == "/opt/mcp"
        assert no_test is False
        assert remaining == ["python", "server.py"]

    def test_extracts_no_test_flag(self):
        """Parse --no-test flag."""
        args = ["npx", "-y", "server", "--no-test"]
        env, cwd, no_test, remaining = _extract_add_options(args)

        assert env == {}
        assert cwd is None
        assert no_test is True
        assert remaining == ["npx", "-y", "server"]

    def test_extracts_all_options(self):
        """Parse all options together."""
        args = ["npx", "--env=KEY=val", "--cwd=/tmp", "--no-test", "-y", "pkg"]
        env, cwd, no_test, remaining = _extract_add_options(args)

        assert env == {"KEY": "val"}
        assert cwd == "/tmp"
        assert no_test is True
        assert remaining == ["npx", "-y", "pkg"]


@pytest.mark.asyncio
async def test_mcp_add_with_no_test_skips_test(
    monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock
):
    """Ensure --no-test flag skips automatic server test."""
    manager = SimpleNamespace(
        add_server=AsyncMock(),
        show_server=AsyncMock(return_value=None),
        test_server=AsyncMock(),  # Should NOT be called
    )
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))

    result = await registry.execute(
        ctx,
        "/mcp add github npx -y @modelcontextprotocol/server-github --no-test",
    )

    assert result is not None and result.success
    assert "test skipped" in result.message
    manager.add_server.assert_awaited_once()
    manager.test_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_add_reports_test_failure(
    monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock
):
    """Ensure test failure after add shows warning but keeps config."""

    async def _fail(*_args, **_kwargs):
        raise ValueError("Missing required environment variables")

    manager = SimpleNamespace(
        add_server=AsyncMock(),
        show_server=AsyncMock(return_value=None),
        test_server=_fail,
    )
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))
    ctx.ui.spinner = MagicMock(return_value=nullcontext())

    result = await registry.execute(
        ctx,
        "/mcp add github npx -y server --env=TOKEN=${missing}",
    )

    # Add succeeds but test fails - returns warning
    assert result is not None and not result.success
    assert "added but configuration error" in result.message
    assert "Missing required environment" in result.message
    manager.add_server.assert_awaited_once()


@pytest.mark.asyncio
async def test_mcp_add_reports_timeout(
    monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock
):
    """Ensure timeout during test shows appropriate message."""

    async def _timeout(*_args, **_kwargs):
        raise TimeoutError()

    manager = SimpleNamespace(
        add_server=AsyncMock(),
        show_server=AsyncMock(return_value=None),
        test_server=_timeout,
    )
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))
    ctx.ui.spinner = MagicMock(return_value=nullcontext())

    # Mock asyncio.wait_for to propagate our timeout
    async def mock_wait_for(coro, timeout):
        return await coro

    monkeypatch.setattr("asyncio.wait_for", mock_wait_for)

    result = await registry.execute(ctx, "/mcp add slow npx -y slow-server")

    assert result is not None and not result.success
    # TimeoutError from test_server is caught
    manager.add_server.assert_awaited_once()
