"""
Merlya Commands - Command handlers.

Implements /help, /hosts, /ssh, /variable, /secret, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.commands.registry import (
    CommandResult,
    command,
    get_registry,
    subcommand,
)
from merlya.persistence.models import Host

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# =============================================================================
# Help Command
# =============================================================================


@command("help", "Show help for commands", "/help [command]", aliases=["h", "?"])
async def cmd_help(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show help for commands."""
    registry = get_registry()

    if args:
        # Help for specific command
        cmd = registry.get(args[0])
        if cmd:
            lines = [
                f"**/{cmd.name}** - {cmd.description}",
                f"Usage: `{cmd.usage}`" if cmd.usage else "",
            ]
            if cmd.subcommands:
                lines.append("\nSubcommands:")
                for name, sub in cmd.subcommands.items():
                    lines.append(f"  `{name}` - {sub.description}")
            return CommandResult(
                success=True,
                message="\n".join(filter(None, lines)),
            )
        return CommandResult(
            success=False,
            message=f"Unknown command: {args[0]}",
        )

    # Show all commands
    lines = ["**Available Commands:**\n"]
    for cmd in registry.all():
        lines.append(f"  `/{cmd.name}` - {cmd.description}")

    lines.append("\nUse `/help <command>` for more details.")
    return CommandResult(success=True, message="\n".join(lines))


# =============================================================================
# Exit Command
# =============================================================================


@command("exit", "Exit Merlya", "/exit", aliases=["quit", "q"])
async def cmd_exit(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Exit Merlya."""
    return CommandResult(
        success=True,
        message="Goodbye!",
        data={"exit": True},
    )


# =============================================================================
# New Command
# =============================================================================


@command("new", "Start a new conversation", "/new")
async def cmd_new(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Start a new conversation."""
    return CommandResult(
        success=True,
        message="Started new conversation.",
        data={"new_conversation": True},
    )


# =============================================================================
# Hosts Commands
# =============================================================================


@command("hosts", "Manage hosts inventory", "/hosts <subcommand>")
async def cmd_hosts(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage hosts inventory."""
    if not args:
        return await cmd_hosts_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help hosts` for available commands.",
        show_help=True,
    )


@subcommand("hosts", "list", "List all hosts", "/hosts list [--tag=<tag>]")
async def cmd_hosts_list(ctx: SharedContext, args: list[str]) -> CommandResult:
    """List all hosts."""
    tag = None
    for arg in args:
        if arg.startswith("--tag="):
            tag = arg[6:]

    if tag:
        hosts = await ctx.hosts.get_by_tag(tag)
    else:
        hosts = await ctx.hosts.get_all()

    if not hosts:
        return CommandResult(
            success=True,
            message="No hosts found. Use `/hosts add <name>` to add one.",
        )

    lines = [f"**Hosts** ({len(hosts)})\n"]
    for h in hosts:
        status_icon = "✓" if h.health_status == "healthy" else "✗"
        tags = f" [{', '.join(h.tags)}]" if h.tags else ""
        lines.append(f"  {status_icon} `{h.name}` - {h.hostname}{tags}")

    return CommandResult(success=True, message="\n".join(lines), data=hosts)


@subcommand("hosts", "add", "Add a new host", "/hosts add <name>")
async def cmd_hosts_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new host."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/hosts add <name>`",
        )

    name = args[0]

    # Check if exists
    existing = await ctx.hosts.get_by_name(name)
    if existing:
        return CommandResult(
            success=False,
            message=f"Host '{name}' already exists.",
        )

    # Prompt for hostname
    hostname = await ctx.ui.prompt(f"Hostname or IP for {name}")
    if not hostname:
        return CommandResult(success=False, message="Hostname required.")

    # Optional port
    port_str = await ctx.ui.prompt("SSH port", default="22")
    port = int(port_str) if port_str.isdigit() else 22

    # Optional username
    username = await ctx.ui.prompt("Username (optional)")

    # Create host
    host = Host(
        name=name,
        hostname=hostname,
        port=port,
        username=username if username else None,
    )

    await ctx.hosts.create(host)

    return CommandResult(
        success=True,
        message=f"Host '{name}' added ({hostname}:{port}).",
    )


@subcommand("hosts", "show", "Show host details", "/hosts show <name>")
async def cmd_hosts_show(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show host details."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts show <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    lines = [
        f"**{host.name}**\n",
        f"  Hostname: `{host.hostname}`",
        f"  Port: `{host.port}`",
        f"  Username: `{host.username or 'default'}`",
        f"  Status: `{host.health_status}`",
        f"  Tags: `{', '.join(host.tags) if host.tags else 'none'}`",
    ]

    if host.os_info:
        lines.append(f"\n  OS: `{host.os_info.name} {host.os_info.version}`")
        lines.append(f"  Kernel: `{host.os_info.kernel}`")

    if host.last_seen:
        lines.append(f"\n  Last seen: `{host.last_seen}`")

    return CommandResult(success=True, message="\n".join(lines), data=host)


@subcommand("hosts", "delete", "Delete a host", "/hosts delete <name>")
async def cmd_hosts_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a host."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts delete <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    confirmed = await ctx.ui.prompt_confirm(f"Delete host '{args[0]}'?")
    if not confirmed:
        return CommandResult(success=True, message="Cancelled.")

    await ctx.hosts.delete(host.id)
    return CommandResult(success=True, message=f"Host '{args[0]}' deleted.")


@subcommand("hosts", "tag", "Add a tag to a host", "/hosts tag <name> <tag>")
async def cmd_hosts_tag(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a tag to a host."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/hosts tag <name> <tag>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    tag = args[1]
    if tag not in host.tags:
        host.tags.append(tag)
        await ctx.hosts.update(host)

    return CommandResult(success=True, message=f"Tag '{tag}' added to '{args[0]}'.")


# =============================================================================
# Variable Commands
# =============================================================================


@command("variable", "Manage variables", "/variable <subcommand>", aliases=["var"])
async def cmd_variable(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage variables."""
    if not args:
        return await cmd_variable_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help variable` for available commands.",
        show_help=True,
    )


@subcommand("variable", "list", "List all variables", "/variable list")
async def cmd_variable_list(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """List all variables."""
    variables = await ctx.variables.get_all()

    if not variables:
        return CommandResult(
            success=True,
            message="No variables set. Use `/variable set <name> <value>` to set one.",
        )

    lines = [f"**Variables** ({len(variables)})\n"]
    for v in variables:
        env_marker = " (env)" if v.is_env else ""
        # Mask value for security
        masked = v.value[:3] + "***" if len(v.value) > 3 else "***"
        lines.append(f"  `@{v.name}` = `{masked}`{env_marker}")

    return CommandResult(success=True, message="\n".join(lines))


@subcommand("variable", "set", "Set a variable", "/variable set <name> <value>")
async def cmd_variable_set(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set a variable."""
    if len(args) < 2:
        return CommandResult(
            success=False,
            message="Usage: `/variable set <name> <value>`",
        )

    name = args[0]
    value = " ".join(args[1:])
    is_env = "--env" in args

    await ctx.variables.set(name, value, is_env=is_env)

    return CommandResult(
        success=True,
        message=f"Variable `@{name}` set.",
    )


@subcommand("variable", "get", "Get a variable value", "/variable get <name>")
async def cmd_variable_get(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Get a variable value."""
    if not args:
        return CommandResult(success=False, message="Usage: `/variable get <name>`")

    var = await ctx.variables.get(args[0])
    if not var:
        return CommandResult(
            success=False,
            message=f"Variable `@{args[0]}` not found.",
        )

    return CommandResult(
        success=True,
        message=f"`@{var.name}` = `{var.value}`",
        data=var.value,
    )


@subcommand("variable", "delete", "Delete a variable", "/variable delete <name>")
async def cmd_variable_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a variable."""
    if not args:
        return CommandResult(success=False, message="Usage: `/variable delete <name>`")

    deleted = await ctx.variables.delete(args[0])
    if deleted:
        return CommandResult(success=True, message=f"Variable `@{args[0]}` deleted.")
    return CommandResult(success=False, message=f"Variable `@{args[0]}` not found.")


# =============================================================================
# Secret Commands
# =============================================================================


@command("secret", "Manage secrets (securely stored)", "/secret <subcommand>")
async def cmd_secret(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage secrets."""
    if not args:
        return await cmd_secret_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help secret` for available commands.",
        show_help=True,
    )


@subcommand("secret", "list", "List all secrets (names only)", "/secret list")
async def cmd_secret_list(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """List all secrets (names only)."""
    secrets = ctx.secrets.list_keys()

    if not secrets:
        return CommandResult(
            success=True,
            message="No secrets stored. Use `/secret set <name>` to add one.",
        )

    lines = [f"**Secrets** ({len(secrets)})\n"]
    for name in secrets:
        lines.append(f"  `@{name}`")

    return CommandResult(success=True, message="\n".join(lines))


@subcommand("secret", "set", "Set a secret (prompted securely)", "/secret set <name>")
async def cmd_secret_set(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set a secret."""
    if not args:
        return CommandResult(success=False, message="Usage: `/secret set <name>`")

    name = args[0]
    value = await ctx.ui.prompt_secret(f"Enter value for '{name}'")

    if not value:
        return CommandResult(success=False, message="Secret cannot be empty.")

    ctx.secrets.set(name, value)

    return CommandResult(
        success=True,
        message=f"Secret `@{name}` set securely.",
    )


@subcommand("secret", "delete", "Delete a secret", "/secret delete <name>")
async def cmd_secret_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a secret."""
    if not args:
        return CommandResult(success=False, message="Usage: `/secret delete <name>`")

    ctx.secrets.delete(args[0])
    return CommandResult(success=True, message=f"Secret `@{args[0]}` deleted.")


# =============================================================================
# SSH Commands
# =============================================================================


@command("ssh", "SSH connection management", "/ssh <subcommand>")
async def cmd_ssh(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """SSH connection management."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/ssh <connect|exec|config|disconnect>`\n"
            "Use `/help ssh` for more details.",
            show_help=True,
        )

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help ssh` for available commands.",
        show_help=True,
    )


@subcommand("ssh", "connect", "Connect to a host", "/ssh connect <host>")
async def cmd_ssh_connect(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Connect to a host."""
    if not args:
        return CommandResult(success=False, message="Usage: `/ssh connect <host>`")

    host_name = args[0].lstrip("@")
    host = await ctx.hosts.get_by_name(host_name)

    if not host:
        return CommandResult(success=False, message=f"Host '{host_name}' not found.")

    try:
        ssh_pool = await ctx.get_ssh_pool()
        await ssh_pool.get_connection(
            host=host.hostname,
            port=host.port,
            username=host.username,
            private_key=host.private_key,
            jump_host=host.jump_host,
        )

        return CommandResult(
            success=True,
            message=f"Connected to `{host_name}` ({host.hostname})",
        )

    except Exception as e:
        logger.error(f"SSH connection failed: {e}")
        return CommandResult(
            success=False,
            message=f"Failed to connect: {e}",
        )


@subcommand("ssh", "exec", "Execute command on host", "/ssh exec <host> <command>")
async def cmd_ssh_exec(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Execute command on a host."""
    if len(args) < 2:
        return CommandResult(
            success=False,
            message="Usage: `/ssh exec <host> <command>`",
        )

    host_name = args[0].lstrip("@")
    command = " ".join(args[1:])

    host = await ctx.hosts.get_by_name(host_name)
    if not host:
        return CommandResult(success=False, message=f"Host '{host_name}' not found.")

    try:
        ssh_pool = await ctx.get_ssh_pool()
        stdout, stderr, exit_code = await ssh_pool.execute(
            host=host.hostname,
            command=command,
            port=host.port,
            username=host.username,
            private_key=host.private_key,
            jump_host=host.jump_host,
        )

        output = stdout or stderr
        status = "✓" if exit_code == 0 else "✗"

        return CommandResult(
            success=exit_code == 0,
            message=f"{status} Exit code: {exit_code}\n```\n{output}\n```",
            data={"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
        )

    except Exception as e:
        logger.error(f"SSH execution failed: {e}")
        return CommandResult(success=False, message=f"Execution failed: {e}")


@subcommand("ssh", "disconnect", "Disconnect from a host", "/ssh disconnect <host>")
async def cmd_ssh_disconnect(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Disconnect from a host."""
    ssh_pool = await ctx.get_ssh_pool()

    if args:
        host_name = args[0].lstrip("@")
        await ssh_pool.disconnect(host_name)
        return CommandResult(success=True, message=f"Disconnected from `{host_name}`.")

    await ssh_pool.disconnect_all()
    return CommandResult(success=True, message="Disconnected from all hosts.")


# =============================================================================
# Language Command
# =============================================================================


@command("language", "Change interface language", "/language <fr|en>", aliases=["lang"])
async def cmd_language(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Change interface language."""
    if not args:
        current = ctx.i18n.language
        return CommandResult(
            success=True,
            message=f"Current language: `{current}`\nUsage: `/language <fr|en>`",
        )

    lang = args[0].lower()
    if lang not in ["fr", "en"]:
        return CommandResult(
            success=False,
            message="Supported languages: `fr`, `en`",
        )

    ctx.i18n.set_language(lang)
    return CommandResult(
        success=True,
        message=ctx.t("language.changed", lang=lang),
    )


# =============================================================================
# Health Command
# =============================================================================


@command("health", "Show system health status", "/health")
async def cmd_health(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Show system health status."""
    from merlya.health import run_startup_checks

    health = await run_startup_checks()

    lines = ["**Health Status**\n"]
    for check in health.checks:
        icon = "✓" if check.status.value == "ok" else "✗"
        lines.append(f"  {icon} {check.message}")

    if health.capabilities:
        lines.append("\n**Capabilities:**")
        for cap, enabled in health.capabilities.items():
            status = "enabled" if enabled else "disabled"
            lines.append(f"  {cap}: `{status}`")

    return CommandResult(success=True, message="\n".join(lines), data=health)


# =============================================================================
# Initialize all commands
# =============================================================================


def init_commands() -> None:
    """Initialize all command handlers (import triggers registration)."""
    # Commands are registered when the decorators are evaluated
    logger.debug("Commands initialized")
