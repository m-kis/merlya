"""
Merlya Tools - System tools.

Provides tools for system monitoring and diagnostics.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import contextlib
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


def _validate_username(user: str | None) -> str | None:
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

    Uses df -P (POSIX format) with LANG=C for locale-independent output.

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

    # Use POSIX format (-P) for consistent output across systems
    # -k for kilobytes (more reliable than -h for parsing)
    cmd = f"LANG=C LC_ALL=C df -Pk {quoted_path} 2>/dev/null | tail -1"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if not result.success:
        return result

    try:
        output = result.data.get("stdout", "").strip()
        disk_info = _parse_df_posix(output, path, threshold)
        if disk_info:
            return ToolResult(success=True, data=disk_info)
    except (IndexError, ValueError) as e:
        logger.warning(f"⚠️ Failed to parse df output: {e}")

    # Fallback: try human-readable format
    cmd = f"LANG=C df -h {quoted_path} 2>/dev/null | tail -1"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        output = result.data.get("stdout", "").strip()
        disk_info = _parse_df_human(output, path, threshold)
        if disk_info:
            return ToolResult(success=True, data=disk_info)

    return ToolResult(
        success=False,
        data={"raw": result.data.get("stdout", "") if result.data else ""},
        error="❌ Failed to parse disk usage",
    )


def _parse_df_posix(output: str, path: str, threshold: int) -> dict | None:
    """Parse df -Pk output (POSIX format, kilobytes)."""
    if not output:
        return None

    parts = output.split()
    if len(parts) < 5:
        return None

    # Find the percentage column (contains %)
    pct_idx = -1
    for i, part in enumerate(parts):
        if "%" in part:
            pct_idx = i
            break

    if pct_idx < 3:
        return None

    try:
        size_kb = int(parts[pct_idx - 3])
        used_kb = int(parts[pct_idx - 2])
        avail_kb = int(parts[pct_idx - 1])
        use_pct = int(parts[pct_idx].rstrip("%"))
        mount = parts[pct_idx + 1] if len(parts) > pct_idx + 1 else path

        return {
            "filesystem": parts[0],
            "size": _format_size(size_kb * 1024),
            "used": _format_size(used_kb * 1024),
            "available": _format_size(avail_kb * 1024),
            "size_bytes": size_kb * 1024,
            "used_bytes": used_kb * 1024,
            "available_bytes": avail_kb * 1024,
            "use_percent": use_pct,
            "mount": mount,
            "warning": use_pct >= threshold,
        }
    except (ValueError, IndexError):
        return None


def _parse_df_human(output: str, path: str, threshold: int) -> dict | None:
    """Parse df -h output (human-readable, fallback)."""
    if not output:
        return None

    parts = output.split()
    if len(parts) < 5:
        return None

    # Find percentage
    pct_idx = -1
    for i, part in enumerate(parts):
        if "%" in part:
            pct_idx = i
            break

    if pct_idx < 3:
        return None

    try:
        use_pct = int(parts[pct_idx].rstrip("%"))
        mount = parts[pct_idx + 1] if len(parts) > pct_idx + 1 else path

        return {
            "filesystem": parts[0],
            "size": parts[pct_idx - 3],
            "used": parts[pct_idx - 2],
            "available": parts[pct_idx - 1],
            "use_percent": use_pct,
            "mount": mount,
            "warning": use_pct >= threshold,
        }
    except (ValueError, IndexError):
        return None


def _format_size(bytes_val: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "K", "M", "G", "T"]:
        if abs(bytes_val) < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val = bytes_val // 1024
    return f"{bytes_val:.1f}P"


async def check_memory(
    ctx: SharedContext,
    host: str,
    threshold: int = 90,
) -> ToolResult:
    """
    Check memory usage on a host.

    Uses /proc/meminfo for robust parsing (locale-independent).
    Falls back to 'free' command if /proc/meminfo not available.

    Args:
        ctx: Shared context.
        host: Host name.
        threshold: Warning threshold percentage.

    Returns:
        ToolResult with memory usage info.
    """
    if not (0 <= threshold <= 100):
        return ToolResult(success=False, data={}, error="Threshold must be 0-100")

    # Primary: /proc/meminfo (most robust, locale-independent)
    cmd = "LANG=C cat /proc/meminfo 2>/dev/null"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        output = result.data.get("stdout", "")
        mem_info = _parse_proc_meminfo(output, threshold)
        if mem_info:
            return ToolResult(success=True, data=mem_info)

    # Fallback: free -b (bytes, more reliable than -m)
    cmd = "LANG=C LC_ALL=C free -b 2>/dev/null"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        output = result.data.get("stdout", "")
        mem_info = _parse_free_output(output, threshold)
        if mem_info:
            return ToolResult(success=True, data=mem_info)

    # Last resort: macOS vm_stat
    cmd = "vm_stat 2>/dev/null"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        output = result.data.get("stdout", "")
        mem_info = _parse_vm_stat(output, threshold)
        if mem_info:
            return ToolResult(success=True, data=mem_info)

    return ToolResult(
        success=False,
        data={"raw": result.data.get("stdout", "") if result.data else ""},
        error="❌ Failed to parse memory usage (tried /proc/meminfo, free, vm_stat)",
    )


def _parse_proc_meminfo(output: str, threshold: int) -> dict | None:
    """Parse /proc/meminfo output (very stable format)."""
    if not output:
        return None

    data: dict[str, int] = {}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            match = re.search(r"(\d+)", value)
            if match:
                data[key.strip()] = int(match.group(1))

    total_kb = data.get("MemTotal", 0)
    if total_kb == 0:
        return None

    available_kb = data.get("MemAvailable")
    if available_kb is None:
        # Old kernels: calculate from Free + Buffers + Cached
        available_kb = data.get("MemFree", 0) + data.get("Buffers", 0) + data.get("Cached", 0)

    used_kb = total_kb - available_kb
    use_percent = round((used_kb / total_kb) * 100, 1)

    return {
        "total_mb": total_kb // 1024,
        "used_mb": used_kb // 1024,
        "available_mb": available_kb // 1024,
        "buffers_mb": data.get("Buffers", 0) // 1024,
        "cached_mb": data.get("Cached", 0) // 1024,
        "use_percent": use_percent,
        "warning": use_percent >= threshold,
    }


def _parse_free_output(output: str, threshold: int) -> dict | None:
    """Parse 'free -b' output (bytes for precision)."""
    if not output:
        return None

    for line in output.splitlines():
        # Match "Mem:" line (case-insensitive for different locales)
        if line.lower().startswith("mem:") or line.lower().startswith("mém:"):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    total = int(parts[1])
                    used = int(parts[2])
                    # available is in column 7 for newer 'free', column 4 for older
                    available = int(parts[6]) if len(parts) > 6 else int(parts[3])

                    if total == 0:
                        return None

                    use_percent = round((used / total) * 100, 1)

                    return {
                        "total_mb": total // (1024 * 1024),
                        "used_mb": used // (1024 * 1024),
                        "available_mb": available // (1024 * 1024),
                        "use_percent": use_percent,
                        "warning": use_percent >= threshold,
                    }
                except (ValueError, IndexError):
                    continue

    return None


def _parse_vm_stat(output: str, threshold: int) -> dict | None:
    """Parse macOS vm_stat output."""
    if not output or ("vm_stat" not in output.lower() and "page" not in output.lower()):
        return None

    page_size = 4096  # Default
    data: dict[str, int] = {}

    for line in output.splitlines():
        if "page size" in line.lower():
            match = re.search(r"(\d+)", line)
            if match:
                page_size = int(match.group(1))
        elif ":" in line:
            key, value = line.split(":", 1)
            match = re.search(r"(\d+)", value)
            if match:
                data[key.strip().lower()] = int(match.group(1))

    free_pages = data.get("pages free", 0)
    active_pages = data.get("pages active", 0)
    inactive_pages = data.get("pages inactive", 0)
    wired_pages = data.get("pages wired down", 0)
    compressed = data.get("pages occupied by compressor", 0)

    total_pages = free_pages + active_pages + inactive_pages + wired_pages + compressed
    if total_pages == 0:
        return None

    used_pages = active_pages + wired_pages + compressed
    total_mb = (total_pages * page_size) // (1024 * 1024)
    used_mb = (used_pages * page_size) // (1024 * 1024)
    available_mb = total_mb - used_mb
    use_percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0

    return {
        "total_mb": total_mb,
        "used_mb": used_mb,
        "available_mb": available_mb,
        "use_percent": use_percent,
        "warning": use_percent >= threshold,
    }


async def check_cpu(
    ctx: SharedContext,
    host: str,
    threshold: float = 80.0,
) -> ToolResult:
    """
    Check CPU usage on a host.

    Uses /proc/loadavg + nproc for Linux, sysctl for macOS/BSD.
    All commands use LANG=C for locale-independent output.

    Args:
        ctx: Shared context.
        host: Host name.
        threshold: Warning threshold percentage.

    Returns:
        ToolResult with CPU usage info.
    """
    if not (0 <= threshold <= 100):
        return ToolResult(success=False, data={}, error="Threshold must be 0-100")

    # Primary: Linux /proc/loadavg + nproc
    cmd = "LANG=C cat /proc/loadavg 2>/dev/null && (nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo 2>/dev/null)"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        cpu_info = _parse_loadavg_nproc(result.data.get("stdout", ""), threshold)
        if cpu_info:
            return ToolResult(success=True, data=cpu_info)

    # Fallback: macOS/BSD sysctl
    cmd = "LANG=C sysctl -n vm.loadavg hw.ncpu 2>/dev/null"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        cpu_info = _parse_sysctl_load(result.data.get("stdout", ""), threshold)
        if cpu_info:
            return ToolResult(success=True, data=cpu_info)

    # Last resort: uptime parsing (works on most systems)
    cmd = "LANG=C uptime && (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)"
    result = await ssh_execute(ctx, host, cmd, timeout=15)

    if result.success and result.data:
        cpu_info = _parse_uptime_load(result.data.get("stdout", ""), threshold)
        if cpu_info:
            return ToolResult(success=True, data=cpu_info)

    return ToolResult(
        success=False,
        data={"raw": result.data.get("stdout", "") if result.data else ""},
        error="❌ Failed to parse CPU usage (tried /proc/loadavg, sysctl, uptime)",
    )


def _parse_loadavg_nproc(output: str, threshold: float) -> dict | None:
    """Parse /proc/loadavg + nproc output."""
    if not output:
        return None

    lines = output.strip().split("\n")
    if len(lines) < 2:
        return None

    try:
        # /proc/loadavg format: "0.15 0.10 0.05 1/234 5678"
        load_parts = lines[0].split()
        if len(load_parts) < 3:
            return None

        load_1m = float(load_parts[0])
        load_5m = float(load_parts[1])
        load_15m = float(load_parts[2])
        cpu_count = int(lines[1].strip())

        if cpu_count <= 0:
            cpu_count = 1

        use_percent = round((load_1m / cpu_count) * 100, 1)

        return {
            "load_1m": load_1m,
            "load_5m": load_5m,
            "load_15m": load_15m,
            "cpu_count": cpu_count,
            "use_percent": use_percent,
            "warning": use_percent >= threshold,
        }
    except (ValueError, IndexError):
        return None


def _parse_sysctl_load(output: str, threshold: float) -> dict | None:
    """Parse macOS/BSD sysctl vm.loadavg hw.ncpu output."""
    if not output:
        return None

    lines = output.strip().split("\n")
    if len(lines) < 2:
        return None

    try:
        # vm.loadavg format: "{ 0.42 0.35 0.28 }" or "0.42 0.35 0.28"
        load_line = lines[0].strip().strip("{}").strip()
        load_parts = load_line.split()

        if len(load_parts) < 3:
            return None

        load_1m = float(load_parts[0])
        load_5m = float(load_parts[1])
        load_15m = float(load_parts[2])
        cpu_count = int(lines[1].strip())

        if cpu_count <= 0:
            cpu_count = 1

        use_percent = round((load_1m / cpu_count) * 100, 1)

        return {
            "load_1m": load_1m,
            "load_5m": load_5m,
            "load_15m": load_15m,
            "cpu_count": cpu_count,
            "use_percent": use_percent,
            "warning": use_percent >= threshold,
        }
    except (ValueError, IndexError):
        return None


def _parse_uptime_load(output: str, threshold: float) -> dict | None:
    """Parse uptime + cpu count output (fallback for any system)."""
    if not output:
        return None

    lines = output.strip().split("\n")
    if not lines:
        return None

    try:
        uptime_line = lines[0]

        # Extract load averages from uptime output
        # Format varies: "load average: 0.42, 0.35, 0.28" or "load averages: 0.42 0.35 0.28"
        match = re.search(r"load averages?:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", uptime_line)
        if not match:
            return None

        load_1m = float(match.group(1))
        load_5m = float(match.group(2))
        load_15m = float(match.group(3))

        cpu_count = 1
        if len(lines) > 1:
            with contextlib.suppress(ValueError):
                cpu_count = int(lines[1].strip())

        if cpu_count <= 0:
            cpu_count = 1

        use_percent = round((load_1m / cpu_count) * 100, 1)

        return {
            "load_1m": load_1m,
            "load_5m": load_5m,
            "load_15m": load_15m,
            "cpu_count": cpu_count,
            "use_percent": use_percent,
            "warning": use_percent >= threshold,
        }
    except (ValueError, IndexError):
        return None


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

    # Try Linux first
    result = await ssh_execute(ctx, host, linux_cmd, timeout=15)

    if not result.success or not result.data.get("stdout"):
        # Fallback to BSD ps
        result = await ssh_execute(ctx, host, bsd_cmd, timeout=15)

    if not result.success:
        return result

    try:
        output = result.data.get("stdout", "").strip()
        processes = _parse_ps_output(output, user, filter_name, limit, sort_by)
        return ToolResult(success=True, data=processes)
    except Exception as e:
        logger.warning(f"⚠️ Failed to parse process list: {e}")
        return ToolResult(
            success=False,
            data=[],
            error=f"❌ Failed to parse process list: {e}",
        )


def _parse_ps_output(
    output: str,
    user: str | None,
    filter_name: str | None,
    limit: int,
    sort_by: str,
) -> list[dict]:
    """Parse ps aux output into structured process list."""
    if not output:
        return []

    lines = output.split("\n")
    processes = []

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

    # Sort if BSD ps was used (no native sort)
    if sort_by == "cpu":
        processes.sort(key=lambda p: p["cpu"], reverse=True)
    elif sort_by == "mem":
        processes.sort(key=lambda p: p["mem"], reverse=True)
    elif sort_by == "pid":
        processes.sort(key=lambda p: p["pid"])

    return processes[:limit]


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


async def check_all_disks(
    ctx: SharedContext,
    host: str,
    threshold: int = 90,
    exclude_types: list[str] | None = None,
) -> ToolResult:
    """
    Check disk usage on all mounted filesystems.

    Uses LANG=C for locale-independent output.
    Works on Linux, macOS, and BSD systems.

    Args:
        ctx: Shared context.
        host: Host name.
        threshold: Warning threshold percentage.
        exclude_types: Filesystem types to exclude.

    Returns:
        ToolResult with disk usage info for all mounts.
    """
    if not (0 <= threshold <= 100):
        return ToolResult(success=False, data=[], error="Threshold must be 0-100")

    if exclude_types is None:
        exclude_types = ["tmpfs", "devtmpfs", "squashfs", "overlay", "devfs", "autofs"]

    # Linux with GNU df (supports --exclude-type)
    excludes = " ".join(f"--exclude-type={t}" for t in exclude_types)
    linux_cmd = f"LANG=C LC_ALL=C df -Pk {excludes} 2>/dev/null"

    # BSD/macOS (no --exclude-type, we filter manually)
    bsd_cmd = "LANG=C LC_ALL=C df -Pk 2>/dev/null"

    # Try Linux first
    result = await ssh_execute(ctx, host, linux_cmd, timeout=15)

    if not result.success or not result.data.get("stdout"):
        # Fallback to BSD style
        result = await ssh_execute(ctx, host, bsd_cmd, timeout=15)

    if not result.success:
        return result

    disks: list[dict[str, Any]] = []
    warnings = 0

    try:
        output = result.data.get("stdout", "").strip()
        lines = output.split("\n")

        for line in lines[1:]:  # Skip header
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) < 5:
                continue

            # Find percentage column
            pct_idx = -1
            for i, part in enumerate(parts):
                if "%" in part:
                    pct_idx = i
                    break

            if pct_idx < 3:
                continue

            try:
                filesystem = parts[0]

                # Filter out excluded types by name patterns (for BSD)
                if any(excl in filesystem.lower() for excl in ["devfs", "tmpfs", "map ", "autofs"]):
                    continue

                size_kb = int(parts[pct_idx - 3])
                used_kb = int(parts[pct_idx - 2])
                avail_kb = int(parts[pct_idx - 1])
                use_percent = int(parts[pct_idx].rstrip("%"))
                mount = parts[pct_idx + 1] if len(parts) > pct_idx + 1 else "unknown"

                disk_info = {
                    "filesystem": filesystem,
                    "size": _format_size(size_kb * 1024),
                    "used": _format_size(used_kb * 1024),
                    "available": _format_size(avail_kb * 1024),
                    "size_bytes": size_kb * 1024,
                    "used_bytes": used_kb * 1024,
                    "available_bytes": avail_kb * 1024,
                    "use_percent": use_percent,
                    "mount": mount,
                    "warning": use_percent >= threshold,
                }
                disks.append(disk_info)
                if disk_info["warning"]:
                    warnings += 1
            except (ValueError, IndexError):
                continue

        return ToolResult(
            success=True,
            data={
                "disks": disks,
                "total_count": len(disks),
                "warnings": warnings,
            },
        )

    except Exception as e:
        logger.warning(f"⚠️ Failed to parse disk output: {e}")
        return ToolResult(success=False, data=[], error=f"❌ Failed to parse disk usage: {e}")


async def check_docker(
    ctx: SharedContext,
    host: str,
) -> ToolResult:
    """
    Check Docker status and containers.

    Args:
        ctx: Shared context.
        host: Host name.

    Returns:
        ToolResult with Docker info.
    """
    # Check if Docker is available and get container info
    cmd = """
    if ! command -v docker >/dev/null 2>&1; then
        echo "DOCKER:not-installed"
        exit 0
    fi

    # Check if Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        echo "DOCKER:not-running"
        exit 0
    fi

    echo "DOCKER:running"
    echo "CONTAINERS:"
    docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null | head -20
    echo "IMAGES:"
    docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}' 2>/dev/null | head -10
    """

    result = await ssh_execute(ctx, host, cmd.strip(), timeout=20)

    docker_status = "unknown"
    containers: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    section = None

    if result.data and result.data.get("stdout"):
        for line in result.data["stdout"].strip().split("\n"):
            if line.startswith("DOCKER:"):
                docker_status = line.split(":", 1)[1]
            elif line == "CONTAINERS:":
                section = "containers"
            elif line == "IMAGES:":
                section = "images"
            elif section == "containers" and "|" in line:
                parts = line.split("|")
                if len(parts) >= 3:
                    containers.append(
                        {
                            "name": parts[0],
                            "status": parts[1],
                            "image": parts[2],
                        }
                    )
            elif section == "images" and "|" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    images.append(
                        {
                            "name": parts[0],
                            "size": parts[1],
                        }
                    )

    # Count running vs stopped containers
    running = sum(1 for c in containers if "Up" in c.get("status", ""))
    stopped = len(containers) - running

    return ToolResult(
        success=True,
        data={
            "status": docker_status,
            "containers": containers,
            "images": images,
            "running_count": running,
            "stopped_count": stopped,
            "total_containers": len(containers),
        },
    )
