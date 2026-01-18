"""
Merlya Commands - Host list command.

Implements /hosts list subcommand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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

    # Use Rich table for better display
    ctx.ui.table(
        headers=["Status", "Name", "Hostname", "Port", "Tags"],
        rows=[
            [
                "ok" if h.health_status == "healthy" else "err",
                h.name,
                h.hostname,
                str(h.port),
                ", ".join(h.tags) if h.tags else "-",
            ]
            for h in hosts
        ],
        title=f"Hosts ({len(hosts)})",
    )

    return CommandResult(success=True, message="", data=hosts)


__all__ = ["cmd_hosts_list"]
