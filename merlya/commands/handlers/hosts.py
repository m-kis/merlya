"""
Merlya Commands - Host management handlers.

Implements /hosts command with subcommands: list, add, show, delete,
tag, untag, edit, check, import, export.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

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
from merlya.core.types import HostStatus
from merlya.persistence.models import ElevationMethod, Host

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class _SSHConnectionTestResult(TypedDict):
    success: bool
    latency_ms: int | None
    os_info: str | None
    error: str | None


class _HostCheckResult(TypedDict):
    host: Host
    result: _SSHConnectionTestResult


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


@subcommand("hosts", "add", "Add a new host", "/hosts add <name> [--test]")
async def cmd_hosts_add(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Add a new host. Use --test to verify SSH connectivity before adding."""
    # Parse flags
    test_connection = "--test" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        return CommandResult(success=False, message="Usage: `/hosts add <name> [--test]`")

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

    # Test connection before adding if --test flag is set
    if test_connection:
        ctx.ui.info(f"🔌 Testing SSH connection to {hostname}:{port}...")

        test_result = await _test_ssh_connection(
            ctx, hostname, port, username if username else None
        )

        if not test_result["success"]:
            ctx.ui.warning(f"⚠️ Connection test failed: {test_result['error']}")
            proceed = await ctx.ui.prompt_confirm("Add host anyway?")
            if not proceed:
                return CommandResult(
                    success=False,
                    message=f"❌ Host not added. Connection test failed: {test_result['error']}",
                )
        else:
            ctx.ui.success(f"✅ Connection successful (latency: {test_result['latency_ms']}ms)")

    host = Host(
        name=name,
        hostname=hostname,
        port=port,
        username=username if username else None,
    )

    await ctx.hosts.create(host)

    msg = f"Host '{name}' added ({hostname}:{port})."
    if test_connection:
        msg = f"✅ {msg}"

    return CommandResult(success=True, message=msg)


async def _test_ssh_connection(
    ctx: SharedContext,
    hostname: str,
    port: int,
    username: str | None,
    timeout: int = 10,
) -> _SSHConnectionTestResult:
    """
    Test SSH connection to a host.

    Returns dict with: success, latency_ms, error, os_info
    """
    import time

    from merlya.ssh import SSHConnectionOptions

    try:
        ssh_pool = await ctx.get_ssh_pool()
        opts = SSHConnectionOptions(port=port, connect_timeout=timeout)

        start = time.monotonic()

        # Try to execute a simple command
        result = await ssh_pool.execute(
            host=hostname,
            command="echo ok && uname -s 2>/dev/null || echo unknown",
            timeout=timeout,
            username=username,
            options=opts,
            retry=False,  # Don't retry for connection test
        )

        latency = int((time.monotonic() - start) * 1000)

        if result.exit_code == 0:
            os_info = result.stdout.strip().split("\n")[-1] if result.stdout else "unknown"
            return {
                "success": True,
                "latency_ms": latency,
                "os_info": os_info,
                "error": None,
            }
        else:
            return {
                "success": False,
                "latency_ms": latency,
                "os_info": None,
                "error": result.stderr or "Command failed",
            }

    except Exception as e:
        logger.debug(f"🔌 Connection test failed: {e}")
        return {
            "success": False,
            "latency_ms": None,
            "os_info": None,
            "error": str(e),
        }


@subcommand(
    "hosts",
    "check",
    "Check connectivity to hosts",
    "/hosts check [<name>|--tag=<tag>|--all]",
)
async def cmd_hosts_check(ctx: SharedContext, args: list[str]) -> CommandResult:
    """
    Check SSH connectivity to hosts.

    Examples:
        /hosts check           - Check all hosts
        /hosts check webserver - Check specific host
        /hosts check --tag=prod - Check hosts with tag
        /hosts check --parallel - Check all hosts in parallel
    """
    # Parse options
    parallel = "--parallel" in args
    tag = None
    host_name = None

    for arg in args:
        if arg.startswith("--tag="):
            tag = arg[6:]
        elif not arg.startswith("--"):
            host_name = arg

    # Get hosts to check
    if host_name:
        host = await ctx.hosts.get_by_name(host_name)
        if not host:
            return CommandResult(success=False, message=f"Host '{host_name}' not found.")
        hosts_to_check = [host]
    elif tag:
        hosts_to_check = await ctx.hosts.get_by_tag(tag)
        if not hosts_to_check:
            return CommandResult(success=False, message=f"No hosts found with tag '{tag}'.")
    else:
        hosts_to_check = await ctx.hosts.get_all()
        if not hosts_to_check:
            return CommandResult(success=True, message="No hosts in inventory.")

    ctx.ui.info(f"🔌 Checking {len(hosts_to_check)} host(s)...")

    results: list[_HostCheckResult] = []

    if parallel and len(hosts_to_check) > 1:
        # Parallel check with semaphore to limit concurrent connections
        semaphore = asyncio.Semaphore(10)

        async def check_with_semaphore(host: Host) -> _HostCheckResult:
            async with semaphore:
                result = await _test_ssh_connection(ctx, host.hostname, host.port, host.username)
                return {"host": host, "result": result}

        tasks = [check_with_semaphore(h) for h in hosts_to_check]
        results = await asyncio.gather(*tasks)
    else:
        # Sequential check with progress
        for i, host in enumerate(hosts_to_check):
            ctx.ui.muted(f"  [{i + 1}/{len(hosts_to_check)}] Checking {host.name}...")
            result = await _test_ssh_connection(ctx, host.hostname, host.port, host.username)
            results.append({"host": host, "result": result})

    # Display results table
    healthy = 0
    unhealthy = 0
    rows = []

    for item in results:
        host = item["host"]
        result = item["result"]

        if result["success"]:
            healthy += 1
            status = "✅"
            latency = f"{result['latency_ms']}ms"
            error = "-"
            # Update host health status
            host.health_status = HostStatus.HEALTHY
            await ctx.hosts.update(host)
        else:
            unhealthy += 1
            status = "❌"
            latency = "-"
            error = result["error"][:50] if result["error"] else "Unknown error"
            # Update host health status
            host.health_status = HostStatus.UNREACHABLE
            await ctx.hosts.update(host)

        rows.append([status, host.name, host.hostname, latency, error])

    ctx.ui.table(
        headers=["Status", "Name", "Hostname", "Latency", "Error"],
        rows=rows,
        title=f"🔌 Connectivity Check ({healthy} healthy, {unhealthy} unreachable)",
    )

    if unhealthy == 0:
        return CommandResult(
            success=True,
            message=f"✅ All {healthy} host(s) are reachable.",
        )
    else:
        return CommandResult(
            success=True,
            message=f"⚠️ {unhealthy}/{len(hosts_to_check)} host(s) unreachable.",
        )


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
            f"⚠️ Delete ALL {len(hosts)} hosts? This cannot be undone!"
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

    msg = f"🗑️ Deleted {deleted} host(s). Elevation cache cleared."
    if errors:
        msg += f"\n⚠️ {len(errors)} deletion(s) failed:\n" + "\n".join(f"  - {e}" for e in errors)

    return CommandResult(
        success=len(errors) == 0,
        message=msg,
    )


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
                    ctx.ui.muted(f"⚠️ Skipping invalid tag: {tag}")
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
        message=f"✅ Host `{host.name}` updated:\n"
        f"  - Hostname: `{host.hostname}`\n"
        f"  - Port: `{host.port}`\n"
        f"  - User: `{host.username or 'default'}`\n"
        f"  - Elevation: `{updated_elevation}`\n"
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
