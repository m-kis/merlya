"""
Merlya Tools - System service tools module.

Provides service status checking tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING, Any

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Validation patterns
_VALID_SERVICE_NAME = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_service_name(name: str) -> str | None:
    """Validate service name. Returns error message or None if valid."""
    if not name:
        return "Service name cannot be empty"
    if len(name) > 128:
        return "Service name too long (max 128 chars)"
    if not _VALID_SERVICE_NAME.match(name):
        return f"Invalid service name: {name} (only alphanumeric, -, _, . allowed)"
    return None


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
