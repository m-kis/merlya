"""
Merlya Tools - Service management.

Manage systemd/init services on remote hosts with safety checks.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Literal

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.os_detect import OSFamily, detect_os
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.ssh.types import SSHResult


# Service actions that require confirmation
DANGEROUS_ACTIONS = {"stop", "restart"}

# Critical services that need extra confirmation
CRITICAL_SERVICES = frozenset(
    {
        "sshd",
        "ssh",
        "networking",
        "network",
        "NetworkManager",
        "systemd-networkd",
        "firewalld",
        "iptables",
        "docker",
        "containerd",
        "kubelet",
    }
)


async def manage_service(
    ctx: SharedContext,
    host: str,
    service: str,
    action: Literal["start", "stop", "restart", "reload", "status", "enable", "disable"],
    force: bool = False,
) -> ToolResult:
    """
    Manage a systemd/init service on a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        service: Service name (e.g., nginx, sshd).
        action: Action to perform.
        force: Skip confirmation for dangerous actions.

    Returns:
        ToolResult with service status.
    """
    # Validate service name (prevent injection)
    if not _is_valid_service_name(service):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid service name: {service}",
        )

    # Safety check for dangerous actions
    if action in DANGEROUS_ACTIONS and not force:
        is_critical = service in CRITICAL_SERVICES

        if is_critical:
            msg = f"🚨 {service} is a critical service. Stopping it may disconnect you!"
        else:
            msg = f"⚠️ About to {action} service '{service}' on {host}"

        confirmed = await ctx.ui.prompt_confirm(f"{msg}\nProceed?")
        if not confirmed:
            return ToolResult(
                success=True,
                data={"action": "cancelled", "service": service},
                error=None,
            )

    # Detect OS and choose appropriate command
    os_info = await detect_os(ctx, host)
    cmd = _build_service_command(os_info.family, service, action)

    if not cmd:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Unsupported OS family: {os_info.family.value}",
        )

    logger.info(f"⚡ {action.capitalize()} service '{service}' on {host}...")

    # Execute with elevation if needed
    result = await execute_security_command(ctx, host, cmd, timeout=30)

    # Parse result
    if action == "status":
        return _parse_status_result(service, result)

    if result.exit_code == 0:
        logger.info(f"✅ Service '{service}' {action} successful on {host}")
        return ToolResult(
            success=True,
            data={
                "service": service,
                "action": action,
                "host": host,
                "message": f"Service '{service}' {action} completed",
            },
        )

    # Check for permission denied
    stderr_lower = (result.stderr or "").lower()
    if "permission denied" in stderr_lower or "access denied" in stderr_lower:
        return ToolResult(
            success=False,
            data={"service": service, "action": action, "requires_elevation": True},
            error="❌ Permission denied. Service management requires elevated privileges.",
        )

    return ToolResult(
        success=False,
        data={"service": service, "action": action, "stderr": result.stderr},
        error=f"❌ Failed to {action} service '{service}': {result.stderr or 'Unknown error'}",
    )


async def list_services(
    ctx: SharedContext,
    host: str,
    filter_state: Literal["running", "stopped", "failed", "all"] = "all",
) -> ToolResult:
    """
    List services on a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        filter_state: Filter by service state.

    Returns:
        ToolResult with list of services.
    """
    os_info = await detect_os(ctx, host)

    if os_info.family == OSFamily.MACOS:
        # macOS uses launchctl
        if filter_state == "running":
            cmd = "launchctl list | grep -v '^-'"
        elif filter_state == "stopped":
            cmd = "launchctl list | grep '^-'"
        elif filter_state == "failed":
            cmd = "launchctl list"
        else:
            cmd = "launchctl list"
    elif os_info.family in (OSFamily.LINUX_ALPINE,):
        # Alpine uses OpenRC
        if filter_state == "running":
            cmd = "rc-status -a | grep -E '^\\[.*\\]\\s+started'"
        elif filter_state == "stopped":
            cmd = "rc-status -a | grep -E '^\\[.*\\]\\s+stopped'"
        elif filter_state == "failed":
            cmd = "rc-status -a | grep -E '^\\[.*\\]\\s+failed'"
        else:
            cmd = "rc-status -a"
    else:
        # systemd
        if filter_state == "running":
            cmd = "systemctl list-units --type=service --state=running --no-pager --no-legend"
        elif filter_state == "stopped":
            cmd = "systemctl list-units --type=service --state=inactive --no-pager --no-legend"
        elif filter_state == "failed":
            cmd = "systemctl list-units --type=service --state=failed --no-pager --no-legend"
        else:
            cmd = "systemctl list-units --type=service --no-pager --no-legend"

    result = await execute_security_command(ctx, host, f"LANG=C {cmd}", timeout=30)

    if result.exit_code != 0:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Failed to list services: {result.stderr}",
        )

    services = _parse_service_list(result.stdout, os_info.family)

    return ToolResult(
        success=True,
        data={
            "services": services,
            "total": len(services),
            "filter": filter_state,
        },
    )


def _is_valid_service_name(name: str) -> bool:
    """Validate service name to prevent command injection."""
    import re

    # Allow alphanumeric, dash, underscore, dot, @ (for systemd instances)
    return bool(re.match(r"^[a-zA-Z0-9_\-.@]+$", name)) and len(name) <= 256


def _build_service_command(
    os_family: OSFamily,
    service: str,
    action: str,
) -> str | None:
    """Build the appropriate service command for the OS."""
    if os_family == OSFamily.MACOS:
        # macOS uses launchctl
        launchctl_actions = {
            "start": f"sudo launchctl start {shlex.quote(service)}",
            "stop": f"sudo launchctl stop {shlex.quote(service)}",
            "restart": f"sudo launchctl stop {shlex.quote(service)} && sudo launchctl start {shlex.quote(service)}",
            "status": f"launchctl list | grep -F {shlex.quote(service)}",
        }
        return launchctl_actions.get(action)

    if os_family == OSFamily.LINUX_ALPINE:
        # Alpine uses OpenRC
        rc_actions = {
            "start": f"sudo rc-service {shlex.quote(service)} start",
            "stop": f"sudo rc-service {shlex.quote(service)} stop",
            "restart": f"sudo rc-service {shlex.quote(service)} restart",
            "reload": f"sudo rc-service {shlex.quote(service)} reload",
            "status": f"rc-service {shlex.quote(service)} status",
            "enable": f"sudo rc-update add {shlex.quote(service)} default",
            "disable": f"sudo rc-update del {shlex.quote(service)} default",
        }
        return rc_actions.get(action)

    if os_family == OSFamily.FREEBSD:
        # FreeBSD uses service
        bsd_actions = {
            "start": f"sudo service {shlex.quote(service)} start",
            "stop": f"sudo service {shlex.quote(service)} stop",
            "restart": f"sudo service {shlex.quote(service)} restart",
            "reload": f"sudo service {shlex.quote(service)} reload",
            "status": f"service {shlex.quote(service)} status",
            "enable": f"sudo sysrc {shlex.quote(service)}_enable=YES",
            "disable": f"sudo sysrc {shlex.quote(service)}_enable=NO",
        }
        return bsd_actions.get(action)

    # Default: systemd (most Linux)
    systemd_actions = {
        "start": f"sudo systemctl start {shlex.quote(service)}",
        "stop": f"sudo systemctl stop {shlex.quote(service)}",
        "restart": f"sudo systemctl restart {shlex.quote(service)}",
        "reload": f"sudo systemctl reload {shlex.quote(service)}",
        "status": f"systemctl status {shlex.quote(service)} --no-pager",
        "enable": f"sudo systemctl enable {shlex.quote(service)}",
        "disable": f"sudo systemctl disable {shlex.quote(service)}",
    }
    return systemd_actions.get(action)


def _parse_status_result(service: str, result: SSHResult) -> ToolResult:
    """Parse service status output."""

    stdout = (result.stdout or "").lower()
    stderr = (result.stderr or "").lower()

    # Determine status from output
    if result.exit_code == 0:
        if "running" in stdout or "active (running)" in stdout:
            status = "running"
        elif "activating" in stdout:
            status = "activating"
        elif "failed" in stdout:
            status = "failed"
        elif "inactive" in stdout or "dead" in stdout:
            status = "inactive"
        elif "active" in stdout:
            status = "active"
        else:
            status = "unknown"
    elif result.exit_code == 3:
        # systemctl returns 3 for stopped services
        status = "stopped"
    elif result.exit_code == 4:
        status = "not-found"
    else:
        if "not found" in stdout or "not found" in stderr:
            status = "not-found"
        elif "inactive" in stdout or "dead" in stdout:
            status = "stopped"
        elif "failed" in stdout:
            status = "failed"
        else:
            status = "unknown"

    return ToolResult(
        success=True,
        data={
            "service": service,
            "status": status,
            "active": status in ("running", "active"),
            "raw_output": result.stdout[:500],
        },
    )


def _parse_service_list(output: str, os_family: OSFamily) -> list[dict[str, str | bool | None]]:
    """Parse service list output."""
    services: list[dict[str, str | bool | None]] = []

    for line in output.strip().split("\n"):
        if not line.strip():
            continue

        if os_family == OSFamily.MACOS:
            # launchctl format: PID Status Label
            parts = line.split()
            if len(parts) >= 3:
                services.append(
                    {
                        "name": parts[2],
                        "pid": parts[0] if parts[0] != "-" else None,
                        "status": "running" if parts[0] != "-" else "stopped",
                    }
                )
        elif os_family == OSFamily.LINUX_ALPINE:
            # OpenRC format: [runlevel] status service_name
            # Example: [default] [started] cron
            line = line.strip()
            if line.startswith("[") and "] " in line:
                # Extract runlevel and the rest
                runlevel_end = line.find("] ")
                if runlevel_end > 0:
                    rest = line[runlevel_end + 2 :].strip()
                    if rest.startswith("[") and "] " in rest:
                        # Extract status and service name
                        status_end = rest.find("] ")
                        if status_end > 0:
                            status = rest[1:status_end]  # Remove brackets
                            service_name = rest[status_end + 2 :].strip()
                            if service_name:
                                services.append(
                                    {
                                        "name": service_name,
                                        "status": status,
                                        "active": status == "started",
                                    }
                                )
        else:
            # systemd format: UNIT LOAD ACTIVE SUB DESCRIPTION...
            parts = line.split()
            if len(parts) >= 4 and ".service" in parts[0]:
                name = parts[0].replace(".service", "")
                status = parts[3] if len(parts) > 3 else "unknown"
                services.append(
                    {
                        "name": name,
                        "status": status,
                        "active": parts[2] == "active" if len(parts) > 2 else False,
                    }
                )

    return services
