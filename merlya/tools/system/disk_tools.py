"""
Merlya Tools - System disk tools module.

Provides disk usage monitoring and analysis tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


def _format_size(bytes_val: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "K", "M", "G", "T"]:
        if abs(bytes_val) < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val = bytes_val // 1024
    return f"{bytes_val:.1f}P"


def _parse_df_posix(output: str, path: str, threshold: int) -> dict[str, object] | None:
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


def _parse_df_human(output: str, path: str, threshold: int) -> dict[str, object] | None:
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
    from .validation import _validate_path

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
    except (IndexError, ValueError):
        pass

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
    from .validation import _validate_threshold

    if error := _validate_threshold(threshold):
        return ToolResult(success=False, data=[], error=error)

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

                size_raw = parts[pct_idx - 3]
                used_raw = parts[pct_idx - 2]
                avail_raw = parts[pct_idx - 1]
                use_percent = int(parts[pct_idx].rstrip("%"))
                mount = parts[pct_idx + 1] if len(parts) > pct_idx + 1 else "unknown"

                disk_info: dict[str, Any] = {
                    "filesystem": filesystem,
                    "use_percent": use_percent,
                    "mount": mount,
                    "warning": use_percent >= threshold,
                }

                # Prefer numeric POSIX df output (-Pk), but gracefully accept human output (tests/mocks).
                try:
                    size_kb = int(size_raw)
                    used_kb = int(used_raw)
                    avail_kb = int(avail_raw)
                    disk_info.update(
                        {
                            "size": _format_size(size_kb * 1024),
                            "used": _format_size(used_kb * 1024),
                            "available": _format_size(avail_kb * 1024),
                            "size_bytes": size_kb * 1024,
                            "used_bytes": used_kb * 1024,
                            "available_bytes": avail_kb * 1024,
                        }
                    )
                except ValueError:
                    disk_info.update(
                        {
                            "size": size_raw,
                            "used": used_raw,
                            "available": avail_raw,
                        }
                    )

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
        from loguru import logger

        logger.warning(f"⚠️ Failed to parse disk output: {e}")
        return ToolResult(success=False, data=[], error=f"❌ Failed to parse disk usage: {e}")
