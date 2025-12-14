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

    return CommandResult(
        success=False, message="Usage: `/mcp <list|add|remove|show|test|tools|examples>`"
    )


@subcommand("mcp", "list", "List configured MCP servers", "/mcp list")
async def cmd_mcp_list(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """List MCP servers from configuration."""
    manager = await _manager(ctx)
    servers = await manager.list_servers()
    if not servers:
        return CommandResult(
            success=True, message="ℹ️ No MCP servers configured. Use `/mcp add <name> <command>`."
        )

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


@subcommand(
    "mcp",
    "add",
    "Add an MCP server",
    "/mcp add <name> <command> [args...] [--env=KEY=VALUE] [--cwd=/path] [--no-test]",
)
async def cmd_mcp_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new MCP server configuration and test connectivity."""
    if len(args) < 2:
        return CommandResult(
            success=False,
            message=(
                "Usage: `/mcp add <name> <command> [args...] [--env=KEY=VALUE] [--cwd=/path] [--no-test]`\n\n"
                "**Example:**\n"
                "```\n"
                "/mcp add context7 npx -y @upstash/context7-mcp --env=CONTEXT7_API_KEY=${my-secret}\n"
                "```\n"
                "ℹ️ Use `${secret-name}` to reference secrets stored with `/secret set`"
            ),
        )

    env, cwd, no_test, remaining = _extract_add_options(args[1:])
    name = args[0]
    if not remaining:
        return CommandResult(success=False, message="❌ Missing command to start the MCP server.")

    command = remaining[0]
    cmd_args = remaining[1:]

    manager = await _manager(ctx)
    if await manager.show_server(name) is not None:
        return CommandResult(success=False, message=f"❌ MCP server '{name}' already exists.")

    await manager.add_server(name, command, cmd_args, env, cwd=cwd)
    logger.info(f"✅ MCP server '{name}' added")

    # Skip test if --no-test flag is provided
    if no_test:
        return CommandResult(
            success=True,
            message=f"✅ MCP server '{name}' added (test skipped). Use `/mcp test {name}` to verify later.",
        )

    # Automatically test the server
    return await _test_newly_added_server(ctx, manager, name)


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
        f"- Args: `{' '.join(server.args) if server.args else '-'}`",
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
    except TimeoutError:
        logger.error(f"⏱️ MCP test timed out for {name}")
        return CommandResult(success=False, message=f"❌ Timeout connecting to '{name}' (15s)")
    except Exception as e:
        logger.error(f"❌ MCP test failed for {name}: {e}")
        return CommandResult(success=False, message=f"❌ Failed to connect to '{name}': {e}")

    tool_names = (
        ", ".join([tool.name for tool in result["tools"]]) if result["tools"] else "no tools"
    )
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
        "## 🚀 Quick Add (CLI)\n\n"
        "```bash\n"
        "# Context7 - Code context from documentation\n"
        "/secret set context7-token <your-api-key>\n"
        "/mcp add context7 npx -y @upstash/context7-mcp --env=CONTEXT7_API_KEY=${context7-token}\n\n"
        "# GitHub - Repository management\n"
        "/secret set github-token <your-token>\n"
        "/mcp add github npx -y @modelcontextprotocol/server-github --env=GITHUB_TOKEN=${github-token}\n\n"
        "# Filesystem - Local file access\n"
        "/mcp add fs npx -y @modelcontextprotocol/server-filesystem /path/to/allowed/dir\n"
        "```\n\n"
        "## 📁 Config File Format (~/.merlya/config.yaml)\n\n"
        "```yaml\n"
        "mcp:\n"
        "  servers:\n"
        "    context7:\n"
        "      command: npx\n"
        "      args: [-y, '@upstash/context7-mcp']\n"
        "      env:\n"
        '        CONTEXT7_API_KEY: "${context7-token}"\n'
        "    github:\n"
        "      command: npx\n"
        "      args: [-y, '@modelcontextprotocol/server-github']\n"
        "      env:\n"
        '        GITHUB_TOKEN: "${GITHUB_TOKEN}"\n'
        "```\n\n"
        "## 💡 Tips\n"
        "- Store secrets with `/secret set <name> <value>`\n"
        "- Reference in env with `${secret-name}`\n"
        "- Use `${VAR:-default}` for optional values with defaults\n"
        "- Skip auto-test with `--no-test` flag"
    )
    return CommandResult(success=True, message=f"📋 MCP config examples:\n{example}")


def _extract_add_options(
    args: list[str],
) -> tuple[dict[str, str], str | None, bool, list[str]]:
    """
    Parse add command options from arguments.

    Returns:
        Tuple of (env dict, cwd path, no_test flag, remaining args)
    """
    env: dict[str, str] = {}
    cwd: str | None = None
    no_test: bool = False
    remaining: list[str] = []

    for arg in args:
        if arg.startswith("--env="):
            kv = arg[len("--env=") :]
            if "=" in kv:
                key, val = kv.split("=", 1)
                env[key] = val
        elif arg.startswith("--cwd="):
            cwd = arg[len("--cwd=") :]
        elif arg == "--no-test":
            no_test = True
        else:
            remaining.append(arg)

    return env, cwd, no_test, remaining


async def _test_newly_added_server(
    ctx: SharedContext, manager: MCPManager, name: str
) -> CommandResult:
    """
    Test a newly added MCP server and return appropriate result.

    If test fails, the server config is kept but user is warned.
    """
    try:
        with ctx.ui.spinner(f"⚡ Testing MCP server '{name}'..."):
            result = await asyncio.wait_for(manager.test_server(name), timeout=15)

        tool_names = (
            ", ".join([tool.name for tool in result["tools"]]) if result["tools"] else "no tools"
        )
        return CommandResult(
            success=True,
            message=f"✅ MCP server '{name}' added and connected successfully!\n📦 Tools: {tool_names}",
            data={
                "server": name,
                "tools": [tool.name for tool in result["tools"]],
                "tool_count": result["tool_count"],
            },
        )

    except TimeoutError:
        logger.warning(f"⏱️ MCP test timed out for {name}")
        return CommandResult(
            success=False,
            message=(
                f"⚠️ MCP server '{name}' added but connection timed out (15s).\n"
                f"The server is saved in config. Check:\n"
                f"  • Is the command correct? `/mcp show {name}`\n"
                f"  • Are environment variables set? Use `--env=KEY=${{secret}}`\n"
                f"  • Try again with `/mcp test {name}`"
            ),
        )

    except ValueError as e:
        # Check if the error is specifically about missing environment variables
        error_msg = str(e).lower()
        is_missing_env_error = any(
            keyword in error_msg
            for keyword in ["missing", "env", "secret", "variable", "environment"]
        )

        logger.warning(f"⚠️ MCP test failed for {name}: {e}")

        if is_missing_env_error:
            return CommandResult(
                success=False,
                message=(
                    f"⚠️ MCP server '{name}' added but configuration error:\n"
                    f"❌ {e}\n\n"
                    f"💡 Fix: Use `/secret set <name>` then reference with `--env=KEY=${{name}}`"
                ),
            )
        else:
            return CommandResult(
                success=False,
                message=(
                    f"⚠️ MCP server '{name}' added but configuration error:\n"
                    f"❌ {e}\n\n"
                    f"The server is saved. Debug with `/mcp show {name}` and retry with `/mcp test {name}`"
                ),
            )

    except Exception as e:
        logger.warning(f"⚠️ MCP test failed for {name}: {e}")
        return CommandResult(
            success=False,
            message=(
                f"⚠️ MCP server '{name}' added but connection failed:\n"
                f"❌ {e}\n\n"
                f"The server is saved. Debug with `/mcp show {name}` and retry with `/mcp test {name}`"
            ),
        )


async def _manager(ctx: SharedContext) -> MCPManager:
    """Helper to get MCP manager with correct type."""
    manager = await ctx.get_mcp_manager()
    if manager is None or not isinstance(manager, MCPManager):
        raise TypeError(f"Expected MCPManager instance, got {type(manager).__name__}")
    return manager
