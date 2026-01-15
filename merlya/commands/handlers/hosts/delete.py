"""
Merlya Commands - Host delete commands.

Implements /hosts delete and /hosts flush subcommands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.commands.registry import CommandResult, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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


@subcommand("hosts", "flush", "Delete ALL hosts", "/hosts flush [--force]")
async def cmd_hosts_flush(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete all hosts from the inventory."""
    hosts = await ctx.hosts.get_all()
    if not hosts:
        return CommandResult(success=True, message="No hosts to delete.")

    force = "--force" in args

    if not force:
        confirmed = await ctx.ui.prompt_confirm(
            f"Delete ALL {len(hosts)} hosts? This cannot be undone!"
        )
        if not confirmed:
            return CommandResult(success=True, message="Cancelled.")

    deleted = 0
    errors: list[str] = []
    for host in hosts:
        try:
            await ctx.hosts.delete(host.id)
            deleted += 1
        except Exception as e:
            errors.append(f"{host.name}: {e}")
            logger.warning(f"Failed to delete host {host.name}: {e}")

    # Also clear the elevation method cache
    from merlya.tools.core.ssh_patterns import clear_elevation_method_cache

    clear_elevation_method_cache()

    msg = f"Deleted {deleted} host(s). Elevation cache cleared."
    if errors:
        msg += f"\n{len(errors)} deletion(s) failed:\n" + "\n".join(f"  - {e}" for e in errors)

    return CommandResult(
        success=len(errors) == 0,
        message=msg,
    )


__all__ = ["cmd_hosts_delete", "cmd_hosts_flush"]
