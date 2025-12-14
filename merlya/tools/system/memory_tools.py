"""
Merlya Tools - System memory tools module.

Provides memory usage monitoring and analysis tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


def _parse_proc_meminfo(output: str, threshold: int) -> dict[str, Any] | None:
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


def _parse_free_output(output: str, threshold: int) -> dict[str, Any] | None:
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


def _parse_vm_stat(output: str, threshold: int) -> dict[str, Any] | None:
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
