"""
Merlya Commands - Host import/export commands.

Implements /hosts import and /hosts export subcommands.
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
)
from merlya.commands.registry import CommandResult, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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
        return CommandResult(success=False, message=f"File not found: {file_path}")

    # Security: Validate file path
    is_valid, error_msg = validate_file_path(file_path)
    if not is_valid:
        logger.warning(f"Import blocked: {error_msg} ({file_path})")
        return CommandResult(success=False, message=f"{error_msg}")

    # Security: Check file size
    is_valid, error_msg = check_file_size(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"{error_msg}")

    file_format = detect_import_format(file_path, args)
    ctx.ui.info(f"Importing hosts from `{file_path}` (format: {file_format})...")

    imported, errors = await import_hosts(ctx, file_path, file_format)

    result_msg = f"Imported {imported} host(s)"
    if errors:
        result_msg += f"\n\n{len(errors)} error(s):\n"
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

    ctx.ui.info(f"Exporting {len(hosts)} hosts to `{file_path}`...")

    data = [host_to_dict(h) for h in hosts]
    content = serialize_hosts(data, file_format)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    return CommandResult(success=True, message=f"Exported {len(hosts)} hosts to `{file_path}`")


__all__ = ["cmd_hosts_export", "cmd_hosts_import"]
