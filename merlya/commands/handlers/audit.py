"""
Merlya Commands - Audit handlers.

Implements /audit command for viewing and exporting audit logs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from merlya.audit.logger import AuditEventType, get_audit_logger
from merlya.commands.registry import CommandResult, command, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("audit", "View and export audit logs", "/audit <subcommand>")
async def cmd_audit(ctx: SharedContext, args: list[str]) -> CommandResult:
    """View and export audit logs."""
    if not args:
        return await cmd_audit_recent(ctx, [])

    return CommandResult(
        success=False,
        message=(
            "**Audit Commands:**\n\n"
            "  `/audit recent [limit]` - Show recent audit events\n"
            "  `/audit export [file]` - Export logs to JSON file\n"
            "  `/audit filter <type>` - Filter by event type\n"
            "  `/audit stats` - Show audit statistics\n"
        ),
        show_help=True,
    )


@subcommand("audit", "recent", "Show recent audit events", "/audit recent [limit]")
async def cmd_audit_recent(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show recent audit events."""
    limit = 20
    if args:
        try:
            limit = int(args[0])
            limit = max(1, min(limit, 100))  # Clamp to 1-100
        except ValueError:
            pass

    audit = await get_audit_logger()
    events = await audit.get_recent(limit=limit)

    if not events:
        return CommandResult(
            success=True,
            message="No audit events recorded yet.",
        )

    lines = [f"**Recent Audit Events** (last {len(events)})\n"]
    for event in events:
        status = "✓" if event["success"] else "✗"
        target = f" → {event['target']}" if event.get("target") else ""
        time_str = event["created_at"][:19] if event.get("created_at") else ""
        lines.append(
            f"  {status} `{time_str}` **{event['event_type']}**: {event['action']}{target}"
        )

    return CommandResult(success=True, message="\n".join(lines), data=events)


@subcommand("audit", "export", "Export audit logs to JSON", "/audit export [file]")
async def cmd_audit_export(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Export audit logs to JSON file."""
    # Default filter values
    limit = 1000
    since = None
    positional_args: list[str] = []

    # Parse flags first, then collect remaining positional arguments
    args = args or []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--since":
            if i + 1 >= len(args):
                return CommandResult(
                    success=False,
                    message="Missing value for `--since` flag. Usage: `--since <hours>`",
                )
            try:
                hours = int(args[i + 1])
                since = datetime.now(UTC) - timedelta(hours=hours)
            except ValueError:
                return CommandResult(
                    success=False,
                    message=f"Invalid value for `--since`: `{args[i + 1]}`. Expected an integer (hours).",
                )
            i += 2
        elif arg == "--limit":
            if i + 1 >= len(args):
                return CommandResult(
                    success=False,
                    message="Missing value for `--limit` flag. Usage: `--limit <n>`",
                )
            try:
                limit = int(args[i + 1])
            except ValueError:
                return CommandResult(
                    success=False,
                    message=f"Invalid value for `--limit`: `{args[i + 1]}`. Expected an integer.",
                )
            i += 2
        else:
            # Not a recognized flag, treat as positional argument
            positional_args.append(arg)
            i += 1

    # Determine output path from first positional arg or use default
    if positional_args:
        output_path = Path(positional_args[0]).expanduser()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path.home() / ".merlya" / "exports" / f"audit_{timestamp}.json"

    # Ensure parent directory exists
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return CommandResult(
            success=False,
            message=f"Failed to create directory `{output_path.parent}`: {e}",
        )

    audit = await get_audit_logger()
    json_data = await audit.export_json(limit=limit, since=since)

    # Write to file with error handling
    try:
        output_path.write_text(json_data)
    except OSError as e:
        return CommandResult(
            success=False,
            message=f"Failed to write audit logs to `{output_path}`: {e}",
        )

    return CommandResult(
        success=True,
        message=(
            f"✅ Audit logs exported to: `{output_path}`\n\n"
            f"Use `--since <hours>` to filter by time\n"
            f"Use `--limit <n>` to limit number of events"
        ),
        data={"path": str(output_path)},
    )


@subcommand("audit", "filter", "Filter audit events by type", "/audit filter <type>")
async def cmd_audit_filter(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Filter audit events by type."""
    if not args:
        # List available types
        types = [t.value for t in AuditEventType]
        return CommandResult(
            success=True,
            message=(
                "**Available event types:**\n\n"
                + "\n".join(f"  - `{t}`" for t in types)
                + "\n\nUsage: `/audit filter <type>`"
            ),
        )

    type_str = args[0].lower()

    # Find matching type
    event_type = None
    for t in AuditEventType:
        if t.value == type_str:
            event_type = t
            break

    if not event_type:
        return CommandResult(
            success=False,
            message=f"Unknown event type: `{type_str}`\n\nUse `/audit filter` to see available types.",
        )

    audit = await get_audit_logger()
    events = await audit.get_recent(limit=50, event_type=event_type)

    if not events:
        return CommandResult(
            success=True,
            message=f"No `{type_str}` events found.",
        )

    lines = [f"**{type_str} Events** ({len(events)} found)\n"]
    for event in events:
        status = "✓" if event["success"] else "✗"
        target = f" → {event['target']}" if event.get("target") else ""
        lines.append(f"  {status} {event['action']}{target}")

    return CommandResult(success=True, message="\n".join(lines), data=events)


@subcommand("audit", "stats", "Show audit statistics", "/audit stats")
async def cmd_audit_stats(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Show audit statistics."""
    audit = await get_audit_logger()

    # Get recent events for stats
    events = await audit.get_recent(limit=1000)

    if not events:
        return CommandResult(
            success=True,
            message="No audit events recorded yet.",
        )

    # Calculate stats
    total = len(events)
    success_count = sum(1 for e in events if e["success"])
    fail_count = total - success_count

    # Count by type
    type_counts: dict[str, int] = {}
    for event in events:
        t = event["event_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    lines = [
        "**Audit Statistics**\n",
        f"  Total events: `{total}`",
        f"  Successful: `{success_count}` ({100 * success_count // total if total else 0}%)",
        f"  Failed: `{fail_count}` ({100 * fail_count // total if total else 0}%)",
        "",
        "**By Event Type:**",
    ]

    for event_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  - {event_type}: `{count}`")

    # Observability status
    obs_status = audit.get_observability_status()
    logfire_status = "enabled" if obs_status.logfire_enabled else "disabled"
    sqlite_status = "enabled" if obs_status.sqlite_enabled else "disabled"
    lines.extend(
        [
            "",
            "**Observability:**",
            f"  - Logfire/OTEL: `{logfire_status}`",
            f"  - SQLite: `{sqlite_status}`",
        ]
    )

    return CommandResult(
        success=True,
        message="\n".join(lines),
        data={
            "total": total,
            "success": success_count,
            "failed": fail_count,
            "by_type": type_counts,
        },
    )
