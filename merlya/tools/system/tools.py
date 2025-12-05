"""
Merlya Tools - System tools.

Provides tools for system monitoring and diagnostics.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Validation patterns
_VALID_SERVICE_NAME = re.compile(r"^[a-zA-Z0-9_.-]+$")
_VALID_LOG_LEVEL = ("error", "warn", "info", "debug")
_MAX_PATH_LENGTH = 4096
_MAX_PATTERN_LENGTH = 256


def _validate_path(path: str) -> str | None:
    """Validate file path. Returns error message or None if valid."""
    if not path:
        return "Path cannot be empty"
    if len(path) > _MAX_PATH_LENGTH:
        return f"Path too long (max {_MAX_PATH_LENGTH} chars)"
    if "\x00" in path:
        return "Path contains null bytes"
    return None


def _validate_service_name(name: str) -> str | None:
    """Validate service name. Returns error message or None if valid."""
    if not name:
        return "Service name cannot be empty"
    if len(name) > 128:
        return "Service name too long (max 128 chars)"
    if not _VALID_SERVICE_NAME.match(name):
        return f"Invalid service name: {name} (only alphanumeric, -, _, . allowed)"
    return None


def _validate_username(user: str) -> str | None:
    """Validate username. Returns error message or None if valid."""
    if not user:
        return None  # Optional
    if len(user) > 32:
        return "Username too long (max 32 chars)"
    if not re.match(r"^[a-zA-Z0-9_-]+$", user):
        return f"Invalid username: {user}"
    return None


async def get_system_info(
    ctx: SharedContext,
    host: str,
) -> ToolResult:
    """
    Get system information from a host.

    Args:
        ctx: Shared context.
        host: Host name.

    Returns:
        ToolResult with system info (OS, kernel, uptime, etc.).
    """
    # All commands are fixed strings - no user input
    commands = {
        "hostname": "hostname",
        "os": "grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'\"' -f2 || uname -s",
        "kernel": "uname -r",
        "arch": "uname -m",
        "uptime": "uptime -p 2>/dev/null || uptime",
        "load": "cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || uptime | grep -o 'load.*'",
    }

    info: dict[str, str] = {}

    for key, cmd in commands.items():
        result = await ssh_execute(ctx, host, cmd, timeout=10)
        if result.success and result.data:
            info[key] = result.data.get("stdout", "").strip()

    if info:
        return ToolResult(success=True, data=info)
    return ToolResult(success=False, data={}, error="Failed to get system info")


async def check_disk_usage(
    ctx: SharedContext,
    host: str,
    path: str = "/",
    threshold: int = 90,
) -> ToolResult:
    """
    Check disk usage on a host.

    Args:
        ctx: Shared context.
        host: Host name.
        path: Filesystem path to check.
        threshold: Warning threshold percentage.

    Returns:
        ToolResult with disk usage info.
    """
    # Validate inputs
    if error := _validate_path(path):
        return ToolResult(success=False, data={}, error=error)

    if not (0 <= threshold <= 100):
        return ToolResult(success=False, data={}, error="Threshold must be 0-100")

    quoted_path = shlex.quote(path)
    cmd = f"df -h {quoted_path} | tail -1"
    result = await ssh_execute(ctx, host, cmd, timeout=10)

    if not result.success:
        return result

    try:
        output = result.data.get("stdout", "").strip()
        parts = output.split()
        if len(parts) >= 5:
            disk_info = {
                "filesystem": parts[0],
                "size": parts[1],
                "used": parts[2],
                "available": parts[3],
                "use_percent": int(parts[4].rstrip("%")),
                "mount": parts[5] if len(parts) > 5 else path,
            }

            disk_info["warning"] = disk_info["use_percent"] >= threshold

            return ToolResult(success=True, data=disk_info)
    except (IndexError, ValueError) as e:
        logger.warning(f"Failed to parse disk output: {e}")

    return ToolResult(success=False, data={"raw": output}, error="Failed to parse disk usage")


async def check_memory(
    ctx: SharedContext,
    host: str,
    threshold: int = 90,
) -> ToolResult:
    """
    Check memory usage on a host.

    Args:
        ctx: Shared context.
        host: Host name.
        threshold: Warning threshold percentage.

    Returns:
        ToolResult with memory usage info.
    """
    if not (0 <= threshold <= 100):
        return ToolResult(success=False, data={}, error="Threshold must be 0-100")

    # Fixed command - no user input
    cmd = "free -m | grep -E '^Mem:'"
    result = await ssh_execute(ctx, host, cmd, timeout=10)

    if not result.success:
        return result

    try:
        output = result.data.get("stdout", "").strip()
        parts = output.split()
        if len(parts) >= 3:
            total = int(parts[1])
            used = int(parts[2])
            available = int(parts[6]) if len(parts) > 6 else total - used

            use_percent = round((used / total) * 100, 1) if total > 0 else 0

            mem_info = {
                "total_mb": total,
                "used_mb": used,
                "available_mb": available,
                "use_percent": use_percent,
                "warning": use_percent >= threshold,
            }

            return ToolResult(success=True, data=mem_info)
    except (IndexError, ValueError) as e:
        logger.warning(f"Failed to parse memory output: {e}")

    return ToolResult(success=False, data={"raw": output}, error="Failed to parse memory usage")


async def check_cpu(
    ctx: SharedContext,
    host: str,
    threshold: float = 80.0,
) -> ToolResult:
    """
    Check CPU usage on a host.

    Args:
        ctx: Shared context.
        host: Host name.
        threshold: Warning threshold percentage.

    Returns:
        ToolResult with CPU usage info.
    """
    if not (0 <= threshold <= 100):
        return ToolResult(success=False, data={}, error="Threshold must be 0-100")

    # Fixed command - no user input
    cmd = "cat /proc/loadavg && nproc"
    result = await ssh_execute(ctx, host, cmd, timeout=10)

    if not result.success:
        return result

    try:
        lines = result.data.get("stdout", "").strip().split("\n")
        if len(lines) >= 2:
            load_parts = lines[0].split()
            load_1m = float(load_parts[0])
            load_5m = float(load_parts[1])
            load_15m = float(load_parts[2])
            cpu_count = int(lines[1].strip())

            # Calculate usage percentage (load relative to CPU count)
            use_percent = round((load_1m / cpu_count) * 100, 1) if cpu_count > 0 else 0

            cpu_info = {
                "load_1m": load_1m,
                "load_5m": load_5m,
                "load_15m": load_15m,
                "cpu_count": cpu_count,
                "use_percent": use_percent,
                "warning": use_percent >= threshold,
            }

            return ToolResult(success=True, data=cpu_info)
    except (IndexError, ValueError) as e:
        logger.warning(f"Failed to parse CPU output: {e}")

    return ToolResult(success=False, data={}, error="Failed to parse CPU usage")


async def list_processes(
    ctx: SharedContext,
    host: str,
    user: str | None = None,
    filter_name: str | None = None,
    limit: int = 20,
) -> ToolResult:
    """
    List running processes on a host.

    Args:
        ctx: Shared context.
        host: Host name.
        user: Filter by user.
        filter_name: Filter by process name.
        limit: Maximum processes to return.

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

    # Build command with safe quoting
    cmd = "ps aux --sort=-%cpu"

    if user:
        # User is validated to be alphanumeric only
        cmd = f"ps aux --sort=-%cpu | grep {shlex.quote(f'^{user}')}"

    if filter_name:
        quoted_filter = shlex.quote(filter_name)
        cmd = f"{cmd} | grep -i {quoted_filter} | grep -v grep"

    cmd = f"{cmd} | head -{int(limit) + 1}"  # +1 for header

    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if not result.success:
        return result

    try:
        lines = result.data.get("stdout", "").strip().split("\n")
        processes = []

        for line in lines[1:]:  # Skip header
            parts = line.split(None, 10)
            if len(parts) >= 11:
                try:
                    processes.append(
                        {
                            "user": parts[0],
                            "pid": int(parts[1]),
                            "cpu": float(parts[2]),
                            "mem": float(parts[3]),
                            "command": parts[10][:100],  # Truncate long commands
                        }
                    )
                except ValueError:
                    continue

        return ToolResult(success=True, data=processes)
    except (IndexError, ValueError) as e:
        logger.warning(f"Failed to parse process list: {e}")

    return ToolResult(success=False, data=[], error="Failed to parse processes")


async def check_service_status(
    ctx: SharedContext,
    host: str,
    service: str,
) -> ToolResult:
    """
    Check the status of a systemd service.

    Args:
        ctx: Shared context.
        host: Host name.
        service: Service name.

    Returns:
        ToolResult with service status.
    """
    # Validate service name
    if error := _validate_service_name(service):
        return ToolResult(success=False, data={}, error=error)

    # Service name is validated to be safe (alphanumeric, -, _, . only)
    quoted_service = shlex.quote(service)
    cmd = f"systemctl is-active {quoted_service} && systemctl show {quoted_service} --property=ActiveState,SubState,MainPID"
    result = await ssh_execute(ctx, host, cmd, timeout=10)

    output = result.data.get("stdout", "").strip() if result.data else ""
    stderr = result.data.get("stderr", "") if result.data else ""

    # Parse status
    lines = output.split("\n")
    is_active = lines[0] == "active" if lines else False

    status_info: dict[str, Any] = {
        "service": service,
        "active": is_active,
        "status": lines[0] if lines else "unknown",
    }

    # Parse properties if available
    for line in lines[1:]:
        if "=" in line:
            key, value = line.split("=", 1)
            status_info[key.lower()] = value

    return ToolResult(
        success=True,
        data=status_info,
        error=stderr if not is_active else None,
    )


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
