"""
Merlya Tools - System process tools module.

Provides process listing and analysis tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING, TypedDict

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


_MAX_PATTERN_LENGTH = 256


class _ProcessInfo(TypedDict):
    user: str
    pid: int
    cpu: float
    mem: float
    command: str


def _validate_username(user: str | None) -> str | None:
    """Validate username. Returns error message or None if valid."""
    if not user:
        return None  # Optional
    if len(user) > 32:
        return "Username too long (max 32 chars)"
    if not re.match(r"^[a-zA-Z0-9_-]+$", user):
        return f"Invalid username: {user}"
    return None


def _parse_ps_output(
    output: str,
    user: str | None,
    filter_name: str | None,
    limit: int,
    sort_by: str,
    *,
    already_sorted: bool,
) -> list[_ProcessInfo]:
    """Parse ps aux output into structured process list."""
    if not output:
        return []

    lines = output.split("\n")
    processes: list[_ProcessInfo] = []

    for line in lines[1:]:  # Skip header
        if not line.strip():
            continue

        parts = line.split(None, 10)
        if len(parts) < 11:
            continue

        try:
            proc_user = parts[0]
            pid = int(parts[1])
            cpu = float(parts[2])
            mem = float(parts[3])
            command = parts[10][:200]  # Truncate long commands

            # Apply user filter
            if user and proc_user != user:
                continue

            # Apply name filter (case-insensitive)
            if filter_name and filter_name.lower() not in command.lower():
                continue

            processes.append(
                {
                    "user": proc_user,
                    "pid": pid,
                    "cpu": cpu,
                    "mem": mem,
                    "command": command,
                }
            )
        except (ValueError, IndexError):
            continue

    # Sort only when output isn't already sorted by `ps` itself (BSD/macOS fallback).
    if not already_sorted:
        if sort_by == "cpu":
            processes.sort(key=lambda p: p["cpu"], reverse=True)
        elif sort_by == "mem":
            processes.sort(key=lambda p: p["mem"], reverse=True)
        elif sort_by == "pid":
            processes.sort(key=lambda p: p["pid"])

    return processes[:limit]


async def list_processes(
    ctx: SharedContext,
    host: str,
    user: str | None = None,
    filter_name: str | None = None,
    limit: int = 20,
    sort_by: str = "cpu",
) -> ToolResult:
    """
    List running processes on a host.

    Uses LANG=C for locale-independent output.
    Works on Linux, macOS, and BSD systems.

    Args:
        ctx: Shared context.
        host: Host name.
        user: Filter by user.
        filter_name: Filter by process name.
        limit: Maximum processes to return.
        sort_by: Sort field (cpu, mem, pid).

    Returns:
        ToolResult with process list.
    """
    # Validate inputs
    if error := _validate_username(user):
        return ToolResult(success=False, data=[], error=error)

    if filter_name and len(filter_name) > _MAX_PATTERN_LENGTH:
        return ToolResult(
            success=False, data=[], error=f"Filter too long (max {_MAX_PATTERN_LENGTH} chars)"
        )

    if not (1 <= limit <= 1000):
        return ToolResult(success=False, data=[], error="Limit must be 1-1000")

    if sort_by not in ("cpu", "mem", "pid"):
        sort_by = "cpu"

    # Linux-style ps with sorting (GNU ps)
    sort_map = {"cpu": "-%cpu", "mem": "-%mem", "pid": "pid"}
    linux_cmd = f"LANG=C LC_ALL=C ps aux --sort={sort_map[sort_by]} 2>/dev/null"

    # BSD/macOS style ps (no --sort option)
    bsd_cmd = "LANG=C LC_ALL=C ps aux 2>/dev/null"

    # Apply filters remotely (keep header) to reduce output and match legacy behavior.
    awk_vars: list[str] = []
    awk_terms: list[str] = []
    if user:
        awk_vars.append(f"-v u={shlex.quote(user)}")
        awk_terms.append("$1 == u")
    if filter_name:
        awk_vars.append(f"-v needle={shlex.quote(filter_name)}")
        awk_terms.append("index(tolower($0), tolower(needle))")
    if awk_terms:
        awk_expr = " && ".join(awk_terms)
        awk = f" | awk {' '.join(awk_vars)} 'NR==1 || ({awk_expr})'"
        linux_cmd += awk
        bsd_cmd += awk

    # Try Linux first
    result = await ssh_execute(ctx, host, linux_cmd, timeout=15)
    already_sorted = True

    if not result.success or not result.data.get("stdout"):
        # Fallback to BSD ps
        result = await ssh_execute(ctx, host, bsd_cmd, timeout=15)
        already_sorted = False

    if not result.success:
        return result

    try:
        output = result.data.get("stdout", "").strip()
        processes = _parse_ps_output(
            output,
            user,
            filter_name,
            limit,
            sort_by,
            already_sorted=already_sorted,
        )
        return ToolResult(success=True, data=processes)
    except Exception as e:
        from loguru import logger

        logger.warning(f"⚠️ Failed to parse process list: {e}")
        return ToolResult(
            success=False,
            data=[],
            error=f"❌ Failed to parse process list: {e}",
        )
