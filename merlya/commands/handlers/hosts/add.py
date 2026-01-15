"""
Merlya Commands - Host add command.

Implements /hosts add subcommand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.handlers.hosts_io import validate_port
from merlya.commands.registry import CommandResult, subcommand
from merlya.persistence.models import Host

from .check import test_ssh_connection

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@subcommand("hosts", "add", "Add a new host", "/hosts add <name> [--test]")
async def cmd_hosts_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new host. Use --test to verify SSH connectivity before adding."""
    import re

    # Parse flags
    test_connection = "--test" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        return CommandResult(success=False, message="Usage: `/hosts add <name> [--test]`")

    name = args[0]

    # Validate host name
    if not name or not name.strip():
        return CommandResult(
            success=False,
            message="Host name cannot be empty.",
        )

    # Host names must start with a letter/digit and contain only valid hostname characters
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", name):
        return CommandResult(
            success=False,
            message="Host name must start with a letter or digit and contain only letters, numbers, dots, hyphens, and underscores.",
        )

    existing = await ctx.hosts.get_by_name(name)
    if existing:
        return CommandResult(success=False, message=f"Host '{name}' already exists.")

    hostname = await ctx.ui.prompt(f"Hostname or IP for {name}")
    if not hostname:
        return CommandResult(success=False, message="Hostname required.")

    port_str = await ctx.ui.prompt("SSH port", default="22")
    port = validate_port(port_str)

    username = await ctx.ui.prompt("Username (optional)")

    # Test connection before adding if --test flag is set
    if test_connection:
        ctx.ui.info(f"Testing SSH connection to {hostname}:{port}...")

        test_result = await test_ssh_connection(ctx, hostname, port, username if username else None)

        if not test_result["success"]:
            ctx.ui.warning(f"Connection test failed: {test_result['error']}")
            proceed = await ctx.ui.prompt_confirm("Add host anyway?")
            if not proceed:
                return CommandResult(
                    success=False,
                    message=f"Host not added. Connection test failed: {test_result['error']}",
                )
        else:
            ctx.ui.success(f"Connection successful (latency: {test_result['latency_ms']}ms)")

    host = Host(
        name=name,
        hostname=hostname,
        port=port,
        username=username if username else None,
    )

    await ctx.hosts.create(host)

    msg = f"Host '{name}' added ({hostname}:{port})."
    if test_connection:
        msg = f"[OK] {msg}"

    return CommandResult(success=True, message=msg)


__all__ = ["cmd_hosts_add"]
