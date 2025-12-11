"""
Merlya Commands - MCP management handlers.

Manage MCP servers, discovery, and tool listings.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.mcp import MCPManager

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("mcp", "Manage MCP servers", "/mcp <subcommand>")
async def cmd_mcp(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Entry point for /mcp command."""
    if not args:
        return await cmd_mcp_list(ctx, [])

    action = args[0].lower()
    rest = args[1:]

    if action == "list":
        return await cmd_mcp_list(ctx, rest)
    if action == "add":
        return await cmd_mcp_add(ctx, rest)
    if action == "remove":
        return await cmd_mcp_remove(ctx, rest)
    if action == "show":
        return await cmd_mcp_show(ctx, rest)
    if action == "test":
        return await cmd_mcp_test(ctx, rest)
    if action == "tools":
        return await cmd_mcp_tools(ctx, rest)
    if action == "examples":
        return await cmd_mcp_examples(ctx, rest)

    return CommandResult(success=False, message="Usage: `/mcp <list|add|remove|show|test|tools|examples>`")


@subcommand("mcp", "list", "List configured MCP servers", "/mcp list")
async def cmd_mcp_list(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """List MCP servers from configuration."""
    manager = await _manager(ctx)
    servers = await manager.list_servers()
    if not servers:
        return CommandResult(success=True, message="ℹ️ No MCP servers configured. Use `/mcp add <name> <command>`.")

    ctx.ui.table(
        headers=["Name", "Command", "Args", "Env", "Enabled"],
        rows=[
            [
                srv["name"],
                srv["command"],
                " ".join(srv["args"]) if srv["args"] else "-",
                ", ".join(srv["env_keys"]) if srv["env_keys"] else "-",
                "✅" if srv["enabled"] else "❌",
            ]
            for srv in servers
        ],
        title=f"🛠️ MCP Servers ({len(servers)})",
    )
    names = ", ".join([srv["name"] for srv in servers])
    return CommandResult(success=True, message=f"✅ Configured MCP servers: {names}")


@subcommand("mcp", "add", "Add an MCP server", "/mcp add <name> <command> [args...] [--env=KEY=VALUE] [--cwd=/path]")
async def cmd_mcp_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new MCP server configuration."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/mcp add <name> <command> [args...] [--env=KEY=VALUE] [--cwd=/path]`")

    env, cwd, remaining = _extract_env_and_cwd(args[1:])
    name = args[0]
    if not remaining:
        return CommandResult(success=False, message="❌ Missing command to start the MCP server.")

    command = remaining[0]
    cmd_args = remaining[1:]

    manager = await _manager(ctx)
    if await manager.show_server(name) is not None:
        return CommandResult(success=False, message=f"❌ MCP server '{name}' already exists.")
    await manager.add_server(name, command, cmd_args, env, cwd=cwd)
    return CommandResult(
        success=True,
        message=f"✅ MCP server '{name}' added. Use `/mcp test {name}` to verify.",
    )


@subcommand("mcp", "remove", "Remove an MCP server", "/mcp remove <name>")
async def cmd_mcp_remove(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Remove an MCP server configuration."""
    if not args:
        return CommandResult(success=False, message="Usage: `/mcp remove <name>`")

    name = args[0]
    manager = await _manager(ctx)
    removed = await manager.remove_server(name)
    if not removed:
        return CommandResult(success=False, message=f"❌ MCP server '{name}' not found.")

    return CommandResult(success=True, message=f"✅ MCP server '{name}' removed.")


@subcommand("mcp", "show", "Show MCP server config", "/mcp show <name>")
async def cmd_mcp_show(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Display configuration for a server."""
    if not args:
        return CommandResult(success=False, message="Usage: `/mcp show <name>`")

    name = args[0]
    manager = await _manager(ctx)
    server = await manager.show_server(name)
    if server is None:
        return CommandResult(success=False, message=f"❌ MCP server '{name}' not found.")

    lines = [
        f"**{name}**",
        f"- Command: `{server.command}`",
        f"- Args: `{ ' '.join(server.args) if server.args else '-'}`",
        f"- Env keys: `{', '.join(server.env.keys()) if server.env else 'none'}`",
    ]
    if server.cwd:
        lines.append(f"- CWD: `{server.cwd}`")
    lines.append(f"- Enabled: `{'yes' if server.enabled else 'no'}`")
    return CommandResult(success=True, message="\n".join(lines))


@subcommand("mcp", "test", "Test MCP server connectivity", "/mcp test <name>")
async def cmd_mcp_test(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Test connecting to a server and list available tools."""
    if not args:
        return CommandResult(success=False, message="Usage: `/mcp test <name>`")

    name = args[0]
    manager = await _manager(ctx)
    try:
        with ctx.ui.spinner(f"Testing MCP server '{name}'..."):
            result = await asyncio.wait_for(manager.test_server(name), timeout=15)
    except asyncio.TimeoutError:
        logger.error(f"⏱️ MCP test timed out for {name}")
        return CommandResult(success=False, message=f"❌ Timeout connecting to '{name}' (15s)")
    except Exception as e:
        logger.error(f"❌ MCP test failed for {name}: {e}")
        return CommandResult(success=False, message=f"❌ Failed to connect to '{name}': {e}")

    tool_names = ", ".join([tool.name for tool in result["tools"]]) if result["tools"] else "no tools"
    return CommandResult(
        success=True,
        message=f"✅ Server '{name}' reachable. Tools: {tool_names}",
        data={
            "server": name,
            "tools": [tool.name for tool in result["tools"]],
            "tool_count": result["tool_count"],
        },
    )


@subcommand("mcp", "tools", "List MCP tools", "/mcp tools [<name>]")
async def cmd_mcp_tools(ctx: SharedContext, args: list[str]) -> CommandResult:
    """List MCP tools optionally filtered by server."""
    target = args[0] if args else None
    manager = await _manager(ctx)
    try:
        tools = await manager.list_tools(target)
    except Exception as e:
        logger.error(f"❌ MCP tools error: {e}")
        return CommandResult(success=False, message=f"❌ Failed to list tools: {e}")

    if not tools:
        return CommandResult(success=True, message="ℹ️ No MCP tools available.")

    ctx.ui.table(
        headers=["Server", "Tool", "Description"],
        rows=[
            [
                tool.server,
                tool.name,
                tool.description or "-",
            ]
            for tool in tools
        ],
        title="🧰 MCP Tools",
    )
    return CommandResult(
        success=True,
        message=f"✅ {len(tools)} tool(s) available.",
        data={"tools": [tool.name for tool in tools]},
    )


@subcommand("mcp", "examples", "Show MCP config examples", "/mcp examples")
async def cmd_mcp_examples(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Show example configuration for MCP servers."""
    example = (
        "```toml\n"
        "[mcp.servers.github]\n"
        'command = "npx"\n'
        'args = ["-y", "@modelcontextprotocol/server-github"]\n'
        'env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }\n\n'
        "[mcp.servers.slack]\n"
        'command = "npx"\n'
        'args = ["-y", "@modelcontextprotocol/server-slack"]\n'
        'env = { SLACK_BOT_TOKEN = "${SLACK_BOT_TOKEN}" }\n\n'
        "[mcp.servers.custom]\n"
        'command = "python"\n'
        'args = ["server.py"]\n'
        '# Use ${VAR:-default} for optional env with defaults\n'
        'env = { PORT = "${MCP_PORT:-8080}", HOST = "${MCP_HOST:-localhost}" }\n'
        "```\n\n"
        "**Note:** Secrets can be stored via `/secret set GITHUB_TOKEN <value>`\n"
        "and referenced with `${GITHUB_TOKEN}` in env."
    )
    return CommandResult(success=True, message=f"📋 MCP config examples:\n{example}")


def _extract_env_and_cwd(args: list[str]) -> tuple[dict[str, str], str | None, list[str]]:
    """Parse env/cwd flags from arguments."""
    env: dict[str, str] = {}
    cwd: str | None = None
    remaining: list[str] = []

    for arg in args:
        if arg.startswith("--env="):
            kv = arg[len("--env=") :]
            if "=" in kv:
                key, val = kv.split("=", 1)
                env[key] = val
        elif arg.startswith("--cwd="):
            cwd = arg[len("--cwd=") :]
        else:
            remaining.append(arg)

    return env, cwd, remaining


async def _manager(ctx: SharedContext) -> MCPManager:
    """Helper to get MCP manager with correct type."""
    manager = await ctx.get_mcp_manager()
    if manager is None or not isinstance(manager, MCPManager):
        raise TypeError(
            f"Expected MCPManager instance, got {type(manager).__name__}"
        )
    return manager
