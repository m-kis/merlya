"""
Merlya Commands - Host management handlers.

Implements /hosts command with subcommands: list, add, show, delete,
tag, untag, edit, import, export.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from merlya.commands.handlers.hosts_io import (
    check_file_size,
    detect_export_format,
    detect_import_format,
    host_to_dict,
    import_hosts,
    serialize_hosts,
    validate_file_path,
    validate_port,
    validate_tag,
)
from merlya.commands.registry import CommandResult, command, subcommand
from merlya.persistence.models import Host

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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

    # Use Rich table for better display
    ctx.ui.table(
        headers=["Status", "Name", "Hostname", "Port", "Tags"],
        rows=[
            [
                "✅" if h.health_status == "healthy" else "❌",
                h.name,
                h.hostname,
                str(h.port),
                ", ".join(h.tags) if h.tags else "-",
            ]
            for h in hosts
        ],
        title=f"🖥️ Hosts ({len(hosts)})",
    )

    return CommandResult(success=True, message="", data=hosts)


@subcommand("hosts", "add", "Add a new host", "/hosts add <name>")
async def cmd_hosts_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new host."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts add <name>`")

    name = args[0]

    existing = await ctx.hosts.get_by_name(name)
    if existing:
        return CommandResult(success=False, message=f"Host '{name}' already exists.")

    hostname = await ctx.ui.prompt(f"Hostname or IP for {name}")
    if not hostname:
        return CommandResult(success=False, message="Hostname required.")

    port_str = await ctx.ui.prompt("SSH port", default="22")
    port = validate_port(port_str)

    username = await ctx.ui.prompt("Username (optional)")

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
    is_valid, error_msg = validate_tag(tag)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error_msg}")

    if tag not in host.tags:
        host.tags.append(tag)
        await ctx.hosts.update(host)

    return CommandResult(success=True, message=f"✅ Tag '{tag}' added to '{args[0]}'.")


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


@subcommand("hosts", "edit", "Edit a host", "/hosts edit <name>")
async def cmd_hosts_edit(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Edit a host interactively."""
    if not args:
        return CommandResult(success=False, message="Usage: `/hosts edit <name>`")

    host = await ctx.hosts.get_by_name(args[0])
    if not host:
        return CommandResult(success=False, message=f"Host '{args[0]}' not found.")

    ctx.ui.info(f"⚙️ Editing host `{host.name}`...")
    ctx.ui.muted(f"Current: {host.hostname}:{host.port}, user={host.username or 'default'}")

    hostname = await ctx.ui.prompt("Hostname or IP", default=host.hostname)
    if hostname:
        host.hostname = hostname

    port_str = await ctx.ui.prompt("SSH port", default=str(host.port))
    host.port = validate_port(port_str, default=host.port)

    username = await ctx.ui.prompt("Username", default=host.username or "")
    host.username = username if username else None

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
                    ctx.ui.muted(f"⚠️ Skipping invalid tag: {tag}")
        host.tags = valid_tags

    await ctx.hosts.update(host)

    return CommandResult(
        success=True,
        message=f"✅ Host `{host.name}` updated:\n"
        f"  - Hostname: `{host.hostname}`\n"
        f"  - Port: `{host.port}`\n"
        f"  - User: `{host.username or 'default'}`\n"
        f"  - Tags: `{', '.join(host.tags) if host.tags else 'none'}`",
    )


@subcommand("hosts", "import", "Import hosts from file", "/hosts import <file> [--format=<format>]")
async def cmd_hosts_import(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Import hosts from a file (JSON, YAML, CSV, SSH config, /etc/hosts)."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/hosts import <file> [--format=json|yaml|csv|ssh|etc_hosts]`\n\n"
            "Supported formats:\n"
            '  - `json`: `[{"name": "host1", "hostname": "1.2.3.4", ...}]`\n'
            "  - `yaml`: Same structure as JSON\n"
            "  - `csv`: `name,hostname,port,username,tags`\n"
            "  - `ssh`: SSH config format (~/.ssh/config)\n"
            "  - `etc_hosts`: /etc/hosts format (auto-detected)",
        )

    file_path = Path(args[0]).expanduser()
    if not file_path.exists():
        return CommandResult(success=False, message=f"❌ File not found: {file_path}")

    # Security: Validate file path
    is_valid, error_msg = validate_file_path(file_path)
    if not is_valid:
        logger.warning(f"⚠️ Import blocked: {error_msg} ({file_path})")
        return CommandResult(success=False, message=f"❌ {error_msg}")

    # Security: Check file size
    is_valid, error_msg = check_file_size(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error_msg}")

    file_format = detect_import_format(file_path, args)
    ctx.ui.info(f"📥 Importing hosts from `{file_path}` (format: {file_format})...")

    imported, errors = await import_hosts(ctx, file_path, file_format)

    result_msg = f"✅ Imported {imported} host(s)"
    if errors:
        result_msg += f"\n\n⚠️ {len(errors)} error(s):\n"
        for err in errors[:5]:
            result_msg += f"  - {err}\n"
        if len(errors) > 5:
            result_msg += f"  ... and {len(errors) - 5} more"

    return CommandResult(success=True, message=result_msg)


@subcommand("hosts", "export", "Export hosts to file", "/hosts export <file> [--format=<format>]")
async def cmd_hosts_export(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Export hosts to a file (JSON, YAML, CSV)."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/hosts export <file> [--format=json|yaml|csv]`",
        )

    file_path = Path(args[0]).expanduser()
    file_format = detect_export_format(file_path, args)

    hosts = await ctx.hosts.get_all()
    if not hosts:
        return CommandResult(success=False, message="No hosts to export.")

    ctx.ui.info(f"📤 Exporting {len(hosts)} hosts to `{file_path}`...")

    data = [host_to_dict(h) for h in hosts]
    content = serialize_hosts(data, file_format)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    return CommandResult(success=True, message=f"✅ Exported {len(hosts)} hosts to `{file_path}`")
