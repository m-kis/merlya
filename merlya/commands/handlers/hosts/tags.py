"""
Merlya Commands - Host tag commands.

Implements /hosts tag and /hosts untag subcommands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.handlers.hosts_io import validate_tag
from merlya.commands.registry import CommandResult, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@subcommand("hosts", "tag", "Add a tag to a host", "/hosts tag <name> <tag>")
async def cmd_hosts_tag(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a tag to a host."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/hosts tag <name> <tag>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    tag = args[1]
    is_valid, error_msg = validate_tag(tag)
    if not is_valid:
        return CommandResult(success=False, message=f"{error_msg}")

    if tag not in host.tags:
        host.tags.append(tag)
        await ctx.hosts.update(host)

    return CommandResult(success=True, message=f"Tag '{tag}' added to '{args[0]}'.")


@subcommand("hosts", "untag", "Remove a tag from a host", "/hosts untag <name> <tag>")
async def cmd_hosts_untag(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Remove a tag from a host."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/hosts untag <name> <tag>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    tag = args[1]
    if tag in host.tags:
        host.tags.remove(tag)
        await ctx.hosts.update(host)
        return CommandResult(success=True, message=f"Tag '{tag}' removed from '{args[0]}'.")

    return CommandResult(success=False, message=f"Tag '{tag}' not found on '{args[0]}'.")


__all__ = ["cmd_hosts_tag", "cmd_hosts_untag"]
