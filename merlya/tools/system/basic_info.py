"""
Merlya Tools - System basic info module.

Provides system information collection tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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
