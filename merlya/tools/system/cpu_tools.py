"""
Merlya Tools - System CPU tools module.

Provides CPU usage monitoring and analysis tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING, Any

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


def _parse_loadavg_nproc(output: str, threshold: float) -> dict[str, Any] | None:
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


def _parse_sysctl_load(output: str, threshold: float) -> dict[str, Any] | None:
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


def _parse_uptime_load(output: str, threshold: float) -> dict[str, Any] | None:
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
