"""
Merlya Commands - Host edit command.

Implements /hosts edit and /hosts show subcommands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.handlers.hosts_io import validate_port, validate_tag
from merlya.commands.registry import CommandResult, subcommand
from merlya.persistence.models import ElevationMethod

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@subcommand("hosts", "show", "Show host details", "/hosts show <name>")
async def cmd_hosts_show(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show host details."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts show <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    # Get elevation method display value
    elevation_display = (
        host.elevation_method.value
        if hasattr(host.elevation_method, "value")
        else str(host.elevation_method)
    )

    lines = [
        f"**{host.name}**\n",
        f"  Hostname: `{host.hostname}`",
        f"  Port: `{host.port}`",
        f"  Username: `{host.username or 'default'}`",
        f"  Elevation: `{elevation_display}`",
        f"  Status: `{host.health_status}`",
        f"  Tags: `{', '.join(host.tags) if host.tags else 'none'}`",
    ]

    if host.os_info:
        lines.append(f"\n  OS: `{host.os_info.name} {host.os_info.version}`")
        lines.append(f"  Kernel: `{host.os_info.kernel}`")

    if host.last_seen:
        lines.append(f"\n  Last seen: `{host.last_seen}`")

    return CommandResult(success=True, message="\n".join(lines), data=host)


@subcommand("hosts", "edit", "Edit a host", "/hosts edit <name>")
async def cmd_hosts_edit(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Edit a host interactively."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts edit <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    ctx.ui.info(f"Editing host `{host.name}`...")
    ctx.ui.muted(f"Current: {host.hostname}:{host.port}, user={host.username or 'default'}")

    hostname = await ctx.ui.prompt("Hostname or IP", default=host.hostname)
    if hostname:
        host.hostname = hostname

    port_str = await ctx.ui.prompt("SSH port", default=str(host.port))
    host.port = validate_port(port_str, default=host.port)

    username = await ctx.ui.prompt("Username", default=host.username or "")
    host.username = username if username else None

    # Elevation method - uses ElevationMethod enum
    current_elevation = (
        host.elevation_method.value
        if hasattr(host.elevation_method, "value")
        else str(host.elevation_method)
    )
    elevation = await ctx.ui.prompt(
        "Elevation method (none/sudo/sudo_password/doas/doas_password/su)",
        default=current_elevation,
    )
    # Map elevation input to ElevationMethod enum
    elevation_map = {
        "none": ElevationMethod.NONE,
        "sudo": ElevationMethod.SUDO,
        "sudo_password": ElevationMethod.SUDO_PASSWORD,
        "sudo-password": ElevationMethod.SUDO_PASSWORD,
        "doas": ElevationMethod.DOAS,
        "doas_password": ElevationMethod.DOAS_PASSWORD,
        "doas-password": ElevationMethod.DOAS_PASSWORD,
        "su": ElevationMethod.SU,
        "auto": ElevationMethod.NONE,  # 'auto' maps to NONE (no explicit elevation)
    }
    host.elevation_method = elevation_map.get(elevation.lower(), ElevationMethod.NONE)

    current_tags = ", ".join(host.tags) if host.tags else ""
    tags_str = await ctx.ui.prompt("Tags (comma-separated)", default=current_tags)
    if tags_str:
        valid_tags = []
        for tag_raw in tags_str.split(","):
            tag = tag_raw.strip()
            if tag:
                is_valid, _ = validate_tag(tag)
                if is_valid:
                    valid_tags.append(tag)
                else:
                    ctx.ui.muted(f"Skipping invalid tag: {tag}")
        host.tags = valid_tags

    await ctx.hosts.update(host)

    # Get elevation display value
    updated_elevation = (
        host.elevation_method.value
        if hasattr(host.elevation_method, "value")
        else str(host.elevation_method)
    )

    return CommandResult(
        success=True,
        message=f"Host `{host.name}` updated:\n"
        f"  - Hostname: `{host.hostname}`\n"
        f"  - Port: `{host.port}`\n"
        f"  - User: `{host.username or 'default'}`\n"
        f"  - Elevation: `{updated_elevation}`\n"
        f"  - Tags: `{', '.join(host.tags) if host.tags else 'none'}`",
    )


__all__ = ["cmd_hosts_edit", "cmd_hosts_show"]
