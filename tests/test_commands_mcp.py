"""Tests for /mcp command handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers import init_commands
from merlya.commands.handlers import mcp as mcp_module
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
async def test_mcp_add_parses_env_and_args(monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock):
    """Ensure /mcp add forwards parsed command/args/env to manager."""
    manager = SimpleNamespace(
        add_server=AsyncMock(),
        list_servers=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))

    result = await registry.execute(ctx, "/mcp add github npx -y @modelcontextprotocol/server-github --env=GITHUB_TOKEN=${GITHUB_TOKEN}")

    assert result is not None and result.success
    manager.add_server.assert_awaited_with(
        "github",
        "npx",
        ["-y", "@modelcontextprotocol/server-github"],
        {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        cwd=None,
    )


@pytest.mark.asyncio
async def test_mcp_tools_lists_tools(monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock):
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
async def test_mcp_test_reports_errors(monkeypatch: pytest.MonkeyPatch, registry: CommandRegistry, ctx: MagicMock):
    """Ensure /mcp test surfaces connection errors."""
    async def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    manager = SimpleNamespace(test_server=_raise)
    monkeypatch.setattr(mcp_module, "_manager", AsyncMock(return_value=manager))

    result = await registry.execute(ctx, "/mcp test github")

    assert result is not None and not result.success
    assert "Failed to connect" in result.message
