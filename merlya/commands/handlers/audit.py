"""
Merlya Commands - Audit handlers.

Implements /audit command for viewing and exporting audit logs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
async def cmd_audit_recent(ctx: SharedContext, args: list[str]) -> CommandResult:
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
        lines.append(f"  {status} `{time_str}` **{event['event_type']}**: {event['action']}{target}")

    return CommandResult(success=True, message="\n".join(lines), data=events)


@subcommand("audit", "export", "Export audit logs to JSON", "/audit export [file]")
async def cmd_audit_export(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Export audit logs to JSON file."""
    # Determine output path
    if args:
        output_path = Path(args[0]).expanduser()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path.home() / ".merlya" / "exports" / f"audit_{timestamp}.json"

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get optional filters
    limit = 1000
    since = None

    # Check for --since flag
    for i, arg in enumerate(args):
        if arg == "--since" and i + 1 < len(args):
            try:
                hours = int(args[i + 1])
                since = datetime.now(timezone.utc) - timedelta(hours=hours)
            except ValueError:
                pass
        elif arg == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass

    audit = await get_audit_logger()
    json_data = await audit.export_json(limit=limit, since=since)

    # Write to file
    output_path.write_text(json_data)

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
async def cmd_audit_filter(ctx: SharedContext, args: list[str]) -> CommandResult:
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
async def cmd_audit_stats(ctx: SharedContext, _args: list[str]) -> CommandResult:
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
        f"  Successful: `{success_count}` ({100*success_count//total if total else 0}%)",
        f"  Failed: `{fail_count}` ({100*fail_count//total if total else 0}%)",
        "",
        "**By Event Type:**",
    ]

    for event_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  - {event_type}: `{count}`")

    # Logfire status
    logfire_status = "enabled" if audit._logfire_enabled else "disabled"
    lines.extend([
        "",
        "**Observability:**",
        f"  - Logfire/OTEL: `{logfire_status}`",
        f"  - SQLite: `{'enabled' if audit._db else 'disabled'}`",
    ])

    return CommandResult(
        success=True,
        message="\n".join(lines),
        data={"total": total, "success": success_count, "failed": fail_count, "by_type": type_counts},
    )
