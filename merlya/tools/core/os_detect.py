"""
Merlya Tools - OS detection and command variants.

Provides OS-aware command execution with fallbacks for robustness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.core.context import SharedContext


class OSFamily(Enum):
    """Supported OS families."""

    LINUX_DEBIAN = "debian"
    LINUX_RHEL = "rhel"
    LINUX_ALPINE = "alpine"
    LINUX_ARCH = "arch"
    LINUX_SUSE = "suse"
    LINUX_GENERIC = "linux"
    MACOS = "macos"
    FREEBSD = "freebsd"
    UNKNOWN = "unknown"


@dataclass
class OSInfo:
    """Detected OS information."""

    family: OSFamily
    name: str = ""
    version: str = ""
    kernel: str = ""
    arch: str = ""


@dataclass
class CommandVariant:
    """A command variant with its parser and supported OS families."""

    command: str
    parser: Callable[[str], dict[str, Any]]
    os_families: list[OSFamily] | None = None  # None = all OS
    requires_root: bool = False
    timeout: int = 30


@dataclass
class CommandResult:
    """Result of a command execution with parsed data."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    error: str | None = None
    variant_used: str | None = None


# Cache OS detection per host (cleared on session end)
_os_cache: dict[str, OSInfo] = {}


def clear_os_cache() -> None:
    """Clear the OS detection cache."""
    _os_cache.clear()


async def detect_os(ctx: SharedContext, host: str) -> OSInfo:
    """
    Detect the OS family of a remote host.

    Results are cached per host for the session duration.

    Args:
        ctx: Shared context.
        host: Host name or IP.

    Returns:
        OSInfo with detected OS details.
    """
    if host in _os_cache:
        return _os_cache[host]

    from merlya.tools.security.base import execute_security_command

    os_info = OSInfo(family=OSFamily.UNKNOWN)

    # Try /etc/os-release first (most reliable on Linux)
    cmd = "cat /etc/os-release 2>/dev/null || uname -s 2>/dev/null"
    result = await execute_security_command(ctx, host, cmd, timeout=10)

    if result.exit_code == 0 and result.stdout:
        output = result.stdout.lower()

        # Detect OS family from /etc/os-release
        if "alpine" in output:
            os_info.family = OSFamily.LINUX_ALPINE
        elif "debian" in output or "ubuntu" in output or "mint" in output:
            os_info.family = OSFamily.LINUX_DEBIAN
        elif "rhel" in output or "centos" in output or "fedora" in output or "rocky" in output:
            os_info.family = OSFamily.LINUX_RHEL
        elif "arch" in output or "manjaro" in output:
            os_info.family = OSFamily.LINUX_ARCH
        elif "suse" in output or "opensuse" in output:
            os_info.family = OSFamily.LINUX_SUSE
        elif "darwin" in output:
            os_info.family = OSFamily.MACOS
        elif "freebsd" in output:
            os_info.family = OSFamily.FREEBSD
        elif "linux" in output or "id=" in output:
            os_info.family = OSFamily.LINUX_GENERIC

        # Extract name and version
        for line in result.stdout.split("\n"):
            if line.startswith("PRETTY_NAME="):
                os_info.name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("VERSION_ID="):
                os_info.version = line.split("=", 1)[1].strip().strip('"')

    # Get kernel info
    kernel_result = await execute_security_command(ctx, host, "uname -r 2>/dev/null", timeout=5)
    if kernel_result.exit_code == 0:
        os_info.kernel = kernel_result.stdout.strip()

    # Get arch
    arch_result = await execute_security_command(ctx, host, "uname -m 2>/dev/null", timeout=5)
    if arch_result.exit_code == 0:
        os_info.arch = arch_result.stdout.strip()

    logger.debug(f"🖥️ Detected OS for {host}: {os_info.family.value} ({os_info.name})")
    _os_cache[host] = os_info
    return os_info


async def execute_with_fallback(
    ctx: SharedContext,
    host: str,
    variants: list[CommandVariant],
    description: str = "command",
) -> CommandResult:
    """
    Execute command with OS-aware fallback.

    Tries each variant in order until one succeeds.

    Args:
        ctx: Shared context.
        host: Host name.
        variants: List of command variants to try.
        description: Description for logging.

    Returns:
        CommandResult with parsed data or error.
    """
    from merlya.tools.security.base import execute_security_command

    os_info = await detect_os(ctx, host)
    last_error: str | None = None

    for variant in variants:
        # Skip if OS not supported by this variant
        if variant.os_families and os_info.family not in variant.os_families:
            continue

        try:
            # Execute with LANG=C for consistent output
            cmd = f"LANG=C LC_ALL=C {variant.command}"
            result = await execute_security_command(ctx, host, cmd, timeout=variant.timeout)

            if result.exit_code == 0 and result.stdout:
                try:
                    parsed = variant.parser(result.stdout)
                    return CommandResult(
                        success=True,
                        data=parsed,
                        raw_output=result.stdout,
                        variant_used=variant.command[:50],
                    )
                except (ValueError, IndexError, KeyError) as e:
                    last_error = f"Parse error: {e}"
                    logger.debug(f"⚠️ {description} parse failed with {variant.command[:30]}: {e}")
                    continue
            else:
                last_error = result.stderr or f"Exit code {result.exit_code}"

        except Exception as e:
            last_error = str(e)
            logger.debug(f"⚠️ {description} failed with {variant.command[:30]}: {e}")
            continue

    return CommandResult(
        success=False,
        error=f"All {len(variants)} variants failed for {description}: {last_error}",
    )


# =============================================================================
# Common Parsers
# =============================================================================


def parse_proc_meminfo(output: str) -> dict[str, Any]:
    """
    Parse /proc/meminfo output (very stable format).

    Returns memory values in MB.
    """
    data: dict[str, int] = {}

    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            # Extract numeric value (always in kB)
            match = re.search(r"(\d+)", value)
            if match:
                data[key.strip()] = int(match.group(1))

    total_kb = data.get("MemTotal", 0)
    available_kb = data.get("MemAvailable", data.get("MemFree", 0))
    buffers_kb = data.get("Buffers", 0)
    cached_kb = data.get("Cached", 0)

    # If MemAvailable not present (old kernels), calculate it
    if "MemAvailable" not in data:
        available_kb = data.get("MemFree", 0) + buffers_kb + cached_kb

    used_kb = total_kb - available_kb
    use_percent = round((used_kb / total_kb) * 100, 1) if total_kb > 0 else 0

    return {
        "total_mb": total_kb // 1024,
        "available_mb": available_kb // 1024,
        "used_mb": used_kb // 1024,
        "buffers_mb": buffers_kb // 1024,
        "cached_mb": cached_kb // 1024,
        "use_percent": use_percent,
        "warning": use_percent > 85,
    }


def parse_free_bytes(output: str) -> dict[str, Any]:
    """Parse 'free -b' output (fallback)."""
    lines = output.strip().split("\n")

    for line in lines:
        if line.lower().startswith("mem:"):
            parts = line.split()
            if len(parts) >= 4:
                total = int(parts[1])
                used = int(parts[2])
                available = int(parts[6]) if len(parts) > 6 else int(parts[3])

                use_percent = round((used / total) * 100, 1) if total > 0 else 0

                return {
                    "total_mb": total // (1024 * 1024),
                    "used_mb": used // (1024 * 1024),
                    "available_mb": available // (1024 * 1024),
                    "use_percent": use_percent,
                    "warning": use_percent > 85,
                }

    raise ValueError("Could not parse free output")


def parse_vm_stat(output: str) -> dict[str, Any]:
    """Parse macOS vm_stat output."""
    page_size = 4096  # Default page size
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

    # Calculate memory in bytes then convert to MB
    free_pages = data.get("pages free", 0)
    active_pages = data.get("pages active", 0)
    inactive_pages = data.get("pages inactive", 0)
    wired_pages = data.get("pages wired down", 0)
    compressed_pages = data.get("pages occupied by compressor", 0)

    total_pages = free_pages + active_pages + inactive_pages + wired_pages + compressed_pages
    used_pages = active_pages + wired_pages + compressed_pages

    total_mb = (total_pages * page_size) // (1024 * 1024)
    used_mb = (used_pages * page_size) // (1024 * 1024)
    available_mb = total_mb - used_mb

    use_percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0

    return {
        "total_mb": total_mb,
        "used_mb": used_mb,
        "available_mb": available_mb,
        "use_percent": use_percent,
        "warning": use_percent > 85,
    }


def parse_df_output(output: str) -> dict[str, Any]:
    """Parse df -P output (POSIX format for portability)."""
    lines = output.strip().split("\n")

    # Skip header, get data line
    if len(lines) < 2:
        raise ValueError("No data in df output")

    # Use last line (handles multi-line device names)
    data_line = lines[-1]
    parts = data_line.split()

    if len(parts) < 5:
        raise ValueError(f"Invalid df output format: {data_line}")

    # df -P format: Filesystem 1K-blocks Used Available Use% Mounted
    # Find the percentage column (contains %)
    use_pct_idx = -1
    for i, part in enumerate(parts):
        if "%" in part:
            use_pct_idx = i
            break

    if use_pct_idx < 3:
        raise ValueError("Could not find percentage in df output")

    size_kb = int(parts[use_pct_idx - 3])
    used_kb = int(parts[use_pct_idx - 2])
    avail_kb = int(parts[use_pct_idx - 1])
    use_pct = int(parts[use_pct_idx].rstrip("%"))
    mount = parts[use_pct_idx + 1] if len(parts) > use_pct_idx + 1 else "/"

    return {
        "mount": mount,
        "size": _format_bytes(size_kb * 1024),
        "used": _format_bytes(used_kb * 1024),
        "available": _format_bytes(avail_kb * 1024),
        "size_bytes": size_kb * 1024,
        "used_bytes": used_kb * 1024,
        "available_bytes": avail_kb * 1024,
        "use_percent": use_pct,
        "warning": use_pct > 85,
    }


def _format_bytes(bytes_val: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_val) < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val = bytes_val // 1024
    return f"{bytes_val:.1f}PB"
