"""
Merlya Tools - Cron management.

List and manage crontab entries on remote hosts.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

CronEntryDict = dict[str, str]


@dataclass
class CronEntry:
    """A crontab entry."""

    schedule: str
    command: str
    user: str = ""
    enabled: bool = True
    source: str = ""  # user crontab or system file
    minute: str = ""
    hour: str = ""
    day: str = ""
    month: str = ""
    weekday: str = ""


@dataclass
class CronJob:
    """Parsed cron job with human-readable schedule."""

    entry: CronEntry
    human_schedule: str = ""
    next_run: str = ""


async def list_cron(
    ctx: SharedContext,
    host: str,
    user: str | None = None,
    include_system: bool = True,
) -> ToolResult:
    """
    List crontab entries on a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        user: Specific user (None = current user and root).
        include_system: Include system crontabs (/etc/cron.*).

    Returns:
        ToolResult with cron entries.
    """
    logger.info(f"📋 Listing cron jobs on {host}...")

    entries: list[CronEntryDict] = []

    # Get user crontabs (empty string = current user)
    users = [user] if user else [""]

    for cron_user in users:
        user_entries = await _get_user_crontab(ctx, host, cron_user)
        entries.extend(user_entries)

    # Get root crontab if we have access
    if not user:
        root_entries = await _get_user_crontab(ctx, host, "root")
        entries.extend(root_entries)

    # Get system crontabs
    if include_system:
        system_entries = await _get_system_crontabs(ctx, host)
        entries.extend(system_entries)

    # Parse and format entries
    jobs = []
    for entry in entries:
        job = {
            "schedule": entry.get("schedule", ""),
            "command": entry.get("command", ""),
            "user": entry.get("user", ""),
            "source": entry.get("source", ""),
            "human_schedule": _humanize_schedule(entry.get("schedule", "")),
        }
        jobs.append(job)

    return ToolResult(
        success=True,
        data={
            "jobs": jobs,
            "total": len(jobs),
            "host": host,
        },
    )


async def add_cron(
    ctx: SharedContext,
    host: str,
    schedule: str,
    command: str,
    user: str | None = None,
    comment: str | None = None,
) -> ToolResult:
    """
    Add a crontab entry.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        schedule: Cron schedule (e.g., "0 * * * *" or "@hourly").
        command: Command to execute.
        user: User for the crontab (None = current user).
        comment: Optional comment for the entry.

    Returns:
        ToolResult with status.
    """
    # Validate schedule
    if not _is_valid_schedule(schedule):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid cron schedule: {schedule}",
        )

    # Validate command
    if not command or len(command) > 1000:
        return ToolResult(
            success=False,
            data=None,
            error="❌ Invalid command",
        )

    # Build the cron line safely
    cron_line = f"{schedule} {command}"
    if comment:
        # Sanitize comment: strip newlines and special characters
        safe_comment = comment.replace("\n", " ")[:100]
        cron_line = f"# {safe_comment}\n{cron_line}"

    # Get current crontab and add new entry safely using subprocess
    user_flag = ["-u", user] if user else []

    # Get current crontab
    get_cmd = ["crontab", *user_flag, "-l"]
    get_result = await execute_security_command(ctx, host, " ".join(get_cmd), timeout=15)

    # Build new crontab content
    current_crontab = get_result.stdout if get_result.exit_code == 0 else ""
    new_crontab = current_crontab
    if new_crontab and not new_crontab.endswith("\n"):
        new_crontab += "\n"
    new_crontab += cron_line + "\n"

    # Set new crontab using stdin
    set_cmd = ["crontab", *user_flag, "-"]
    result = await execute_security_command(
        ctx, host, " ".join(set_cmd), timeout=30, input_data=new_crontab
    )

    if result.exit_code != 0:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Failed to add cron job: {result.stderr}",
        )

    logger.info(f"✅ Added cron job on {host}: {schedule} {command[:50]}...")

    return ToolResult(
        success=True,
        data={
            "action": "added",
            "schedule": schedule,
            "command": command,
            "user": user or "current",
            "human_schedule": _humanize_schedule(schedule),
        },
    )


async def remove_cron(
    ctx: SharedContext,
    host: str,
    pattern: str,
    user: str | None = None,
    dry_run: bool = True,
) -> ToolResult:
    """
    Remove crontab entries matching a pattern.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        pattern: Pattern to match (in command or comment).
        user: User for the crontab (None = current user).
        dry_run: If True, only show what would be removed.

    Returns:
        ToolResult with removed entries or preview.
    """
    # Escape pattern for grep using shlex.quote to prevent shell injection
    safe_pattern = shlex.quote(pattern)

    # Safely escape user flag to prevent command injection
    user_flag = f"-u {shlex.quote(user)}" if user else ""

    # Find matching entries
    find_cmd = f"crontab {user_flag} -l 2>/dev/null | grep -n {safe_pattern}"
    result = await execute_security_command(ctx, host, find_cmd, timeout=15)

    if result.exit_code != 0 or not result.stdout.strip():
        return ToolResult(
            success=True,
            data={
                "action": "none",
                "message": f"No entries matching '{pattern}' found",
            },
        )

    matching_lines = result.stdout.strip().split("\n")

    if dry_run:
        return ToolResult(
            success=True,
            data={
                "action": "dry_run",
                "would_remove": matching_lines,
                "count": len(matching_lines),
                "message": f"Would remove {len(matching_lines)} entries. Run with dry_run=False to apply.",
            },
        )

    # Actually remove
    remove_cmd = (
        f"crontab {user_flag} -l 2>/dev/null | grep -v {safe_pattern} | crontab {user_flag} -"
    )
    result = await execute_security_command(ctx, host, remove_cmd, timeout=30)

    if result.exit_code != 0:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Failed to remove cron entries: {result.stderr}",
        )

    logger.info(f"✅ Removed {len(matching_lines)} cron entries on {host}")

    return ToolResult(
        success=True,
        data={
            "action": "removed",
            "removed": matching_lines,
            "count": len(matching_lines),
        },
    )


async def _get_user_crontab(
    ctx: SharedContext,
    host: str,
    user: str,
) -> list[CronEntryDict]:
    """Get crontab for a specific user."""
    # Safely escape user flag to prevent command injection
    user_flag = f"-u {shlex.quote(user)}" if user else ""
    cmd = f"crontab {user_flag} -l 2>/dev/null"
    result = await execute_security_command(ctx, host, cmd, timeout=15)

    entries: list[CronEntryDict] = []
    effective_user = user or "current"

    if result.exit_code == 0 and result.stdout:
        for line in result.stdout.strip().split("\n"):
            entry = _parse_cron_line(line)
            if entry:
                entry["user"] = effective_user
                entry["source"] = f"crontab ({effective_user})"
                entries.append(entry)

    return entries


async def _get_system_crontabs(ctx: SharedContext, host: str) -> list[CronEntryDict]:
    """Get system crontabs from /etc/cron.*."""
    entries: list[CronEntryDict] = []

    # Check /etc/crontab
    crontab_cmd = "cat /etc/crontab 2>/dev/null"
    result = await execute_security_command(ctx, host, crontab_cmd, timeout=15)

    if result.exit_code == 0 and result.stdout:
        for line in result.stdout.strip().split("\n"):
            entry = _parse_cron_line(line, has_user_field=True)
            if entry:
                entry["source"] = "/etc/crontab"
                entries.append(entry)

    # Check /etc/cron.d/
    cron_d_cmd = "cat /etc/cron.d/* 2>/dev/null"
    result = await execute_security_command(ctx, host, cron_d_cmd, timeout=15)

    if result.exit_code == 0 and result.stdout:
        for line in result.stdout.strip().split("\n"):
            entry = _parse_cron_line(line, has_user_field=True)
            if entry:
                entry["source"] = "/etc/cron.d/"
                entries.append(entry)

    return entries


def _parse_cron_line(line: str, has_user_field: bool = False) -> CronEntryDict | None:
    """Parse a crontab line into structured data."""
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith("#"):
        return None

    # Skip variable assignments
    if "=" in line and not line.startswith("@"):
        parts = line.split("=", 1)
        if parts[0].strip().isidentifier():
            return None

    # Handle special schedules (@hourly, @daily, etc.)
    if line.startswith("@"):
        if has_user_field:
            # System crontab format: split into at most 3 parts (schedule, user, command)
            parts = line.split(None, 2)
            if len(parts) >= 3:
                return {
                    "schedule": parts[0],
                    "user": parts[1],
                    "command": parts[2],
                }
            # If missing command, return None
            return None
        else:
            # User crontab format: split into at most 2 parts (schedule, command)
            parts = line.split(None, 1)
            if len(parts) >= 2:
                return {
                    "schedule": parts[0],
                    "user": "",
                    "command": parts[1],
                }
            # If missing command, return None
            return None

    # Standard cron format: m h dom mon dow [user] command
    parts = line.split()
    if len(parts) < 6:
        return None

    if has_user_field:
        # System crontab format: includes user field
        if len(parts) < 7:
            return None
        schedule = " ".join(parts[:5])
        user = parts[5]
        command = " ".join(parts[6:])
    else:
        # User crontab format: no user field
        schedule = " ".join(parts[:5])
        user = ""
        command = " ".join(parts[5:])

    return {
        "schedule": schedule,
        "command": command,
        "user": user,
    }


def _is_valid_schedule(schedule: str) -> bool:
    """Validate cron schedule format with strict regex."""
    # Special schedules
    special = {
        "@reboot",
        "@yearly",
        "@annually",
        "@monthly",
        "@weekly",
        "@daily",
        "@midnight",
        "@hourly",
    }
    if schedule in special:
        return True

    # Strict regex for cron fields (only digits, spaces, asterisks, slashes, commas, hyphens)
    cron_field_pattern = r"^[\d\*/,\-]+$"

    # Standard 5-field format
    parts = schedule.split()
    if len(parts) != 5:
        return False

    # Validate each field with strict regex
    for part in parts:
        if not re.match(cron_field_pattern, part):
            return False

    # Additional validation of each field structure
    return all(_is_valid_cron_field(part, i) for i, part in enumerate(parts))


def _is_valid_cron_field(field: str, position: int) -> bool:
    """Validate a single cron field."""
    # Allow * and */n patterns
    if field == "*":
        return True

    if field.startswith("*/"):
        try:
            int(field[2:])
            return True
        except ValueError:
            return False

    # Allow ranges and lists
    for part in field.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-")
                int(start)
                int(end)
            except ValueError:
                return False
        else:
            try:
                int(part)
            except ValueError:
                # Allow day/month names
                if position >= 3:  # dom, mon, dow
                    continue
                return False

    return True


def _humanize_schedule(schedule: str) -> str:
    """Convert cron schedule to human-readable format."""
    special_map = {
        "@reboot": "At system startup",
        "@yearly": "Once a year (Jan 1st)",
        "@annually": "Once a year (Jan 1st)",
        "@monthly": "Once a month (1st)",
        "@weekly": "Once a week (Sunday)",
        "@daily": "Once a day (midnight)",
        "@midnight": "Once a day (midnight)",
        "@hourly": "Every hour",
    }

    if schedule in special_map:
        return special_map[schedule]

    parts = schedule.split()
    if len(parts) != 5:
        return schedule

    minute, hour, dom, month, dow = parts

    # Simple cases
    if schedule == "* * * * *":
        return "Every minute"
    if schedule == "0 * * * *":
        return "Every hour"
    if schedule == "0 0 * * *":
        return "Daily at midnight"
    if schedule == "0 0 * * 0":
        return "Weekly on Sunday"
    if schedule == "0 0 1 * *":
        return "Monthly on the 1st"

    # Build description
    desc_parts = []

    if minute != "*":
        if minute.startswith("*/"):
            desc_parts.append(f"Every {minute[2:]} minutes")
        else:
            desc_parts.append(f"At minute {minute}")

    if hour != "*":
        if hour.startswith("*/"):
            desc_parts.append(f"every {hour[2:]} hours")
        else:
            desc_parts.append(f"at {hour}:00")

    if dow != "*":
        days = {
            "0": "Sun",
            "1": "Mon",
            "2": "Tue",
            "3": "Wed",
            "4": "Thu",
            "5": "Fri",
            "6": "Sat",
            "7": "Sun",
        }
        desc_parts.append(f"on {days.get(dow, dow)}")

    if dom != "*":
        desc_parts.append(f"on day {dom}")

    if month != "*":
        desc_parts.append(f"in month {month}")

    return " ".join(desc_parts) if desc_parts else schedule
