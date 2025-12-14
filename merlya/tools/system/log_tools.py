"""
Merlya Tools - System log tools module.

Provides log analysis tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


_VALID_LOG_LEVEL = ("error", "warn", "info", "debug")
_MAX_PATTERN_LENGTH = 256
_MAX_PATH_LENGTH = 4096


def _validate_path(path: str) -> str | None:
    """Validate file path. Returns error message or None if valid."""
    if not path:
        return "Path cannot be empty"
    if len(path) > _MAX_PATH_LENGTH:
        return f"Path too long (max {_MAX_PATH_LENGTH} chars)"
    if "\x00" in path:
        return "Path contains null bytes"
    return None


async def analyze_logs(
    ctx: SharedContext,
    host: str,
    log_path: str = "/var/log/syslog",
    pattern: str | None = None,
    lines: int = 50,
    level: str | None = None,
) -> ToolResult:
    """
    Analyze log files on a host.

    Args:
        ctx: Shared context.
        host: Host name.
        log_path: Path to log file.
        pattern: Grep pattern to filter.
        lines: Number of lines to return.
        level: Filter by log level (error, warn, info).

    Returns:
        ToolResult with log entries.
    """
    # Validate inputs
    if error := _validate_path(log_path):
        return ToolResult(success=False, data={}, error=error)

    if pattern and len(pattern) > _MAX_PATTERN_LENGTH:
        return ToolResult(
            success=False, data={}, error=f"Pattern too long (max {_MAX_PATTERN_LENGTH} chars)"
        )

    if level and level.lower() not in _VALID_LOG_LEVEL:
        return ToolResult(
            success=False,
            data={},
            error=f"Invalid level: {level} (use: {', '.join(_VALID_LOG_LEVEL)})",
        )

    if not (1 <= lines <= 10000):
        return ToolResult(success=False, data={}, error="Lines must be 1-10000")

    quoted_path = shlex.quote(log_path)
    cmd = f"tail -n {int(lines)} {quoted_path}"

    if pattern:
        quoted_pattern = shlex.quote(pattern)
        cmd = f"{cmd} | grep -i {quoted_pattern}"

    if level:
        level_upper = level.upper()
        if level_upper == "ERROR":
            cmd = f"{cmd} | grep -iE '(error|err|fail|critical)'"
        elif level_upper == "WARN":
            cmd = f"{cmd} | grep -iE '(warn|warning)'"
        elif level_upper == "INFO":
            cmd = f"{cmd} | grep -iE '(info)'"
        elif level_upper == "DEBUG":
            cmd = f"{cmd} | grep -iE '(debug)'"

    result = await ssh_execute(ctx, host, cmd, timeout=30)

    if not result.success:
        return result

    log_lines = result.data.get("stdout", "").strip().split("\n")
    log_lines = [line for line in log_lines if line]  # Remove empty lines

    return ToolResult(
        success=True,
        data={
            "path": log_path,
            "lines": log_lines,
            "count": len(log_lines),
        },
    )
