"""
Merlya Tools - Security configuration auditing.

Check security configuration on remote hosts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.security.base import (
    DEFAULT_TIMEOUT,
    SecurityResult,
    execute_security_command,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def check_security_config(
    ctx: SharedContext,
    host_name: str,
) -> SecurityResult:
    """
    Check security configuration on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.

    Returns:
        SecurityResult with security config audit.
    """
    try:
        checks: list[dict[str, Any]] = []
        severity = "info"

        # Check SSH config
        ssh_checks, ssh_severity = await _check_ssh_config(ctx, host_name)
        checks.extend(ssh_checks)
        if _severity_higher(ssh_severity, severity):
            severity = ssh_severity

        # Check firewall status
        fw_check, fw_severity = await _check_firewall(ctx, host_name)
        checks.append(fw_check)
        if _severity_higher(fw_severity, severity):
            severity = fw_severity

        # Check automatic updates
        auto_check = await _check_auto_updates(ctx, host_name)
        checks.append(auto_check)

        return SecurityResult(
            success=True,
            data={"checks": checks},
            severity=severity,
        )

    except Exception as e:
        logger.error(f"❌ Failed to check security config on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def _check_ssh_config(
    ctx: SharedContext,
    host_name: str,
) -> tuple[list[dict[str, Any]], str]:
    """Check SSH daemon configuration."""
    checks: list[dict[str, Any]] = []
    severity = "info"

    ssh_config_cmd = (
        "grep -E '^(PermitRootLogin|PasswordAuthentication|"
        "PubkeyAuthentication|PermitEmptyPasswords)' /etc/ssh/sshd_config 2>/dev/null"
    )
    result = await execute_security_command(ctx, host_name, ssh_config_cmd, timeout=DEFAULT_TIMEOUT)

    if result.exit_code != 0:
        return checks, severity

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue

        key, value = parts[0], parts[1]
        status, message, new_severity = _evaluate_ssh_setting(key, value)
        checks.append(
            {
                "setting": key,
                "value": value,
                "status": status,
                "message": message,
            }
        )
        if _severity_higher(new_severity, severity):
            severity = new_severity

    return checks, severity


def _evaluate_ssh_setting(key: str, value: str) -> tuple[str, str, str]:
    """Evaluate SSH setting and return status, message, severity."""
    value_lower = value.lower()

    if key == "PermitRootLogin" and value_lower not in ("no", "prohibit-password"):
        return "warning", "Root login should be disabled", "warning"
    elif key == "PasswordAuthentication" and value_lower == "yes":
        return "warning", "Password authentication should be disabled", "warning"
    elif key == "PermitEmptyPasswords" and value_lower == "yes":
        return "critical", "Empty passwords are allowed!", "critical"

    return "ok", "", "info"


async def _check_firewall(
    ctx: SharedContext,
    host_name: str,
) -> tuple[dict[str, Any], str]:
    """Check firewall status."""
    fw_cmd = (
        "command -v ufw >/dev/null && ufw status | head -1 || "
        "command -v firewall-cmd >/dev/null && firewall-cmd --state || "
        "iptables -L -n 2>/dev/null | head -3"
    )
    result = await execute_security_command(ctx, host_name, fw_cmd, timeout=DEFAULT_TIMEOUT)

    firewall_status = "unknown"
    severity = "info"

    if result.stdout:
        stdout_lower = result.stdout.lower()
        if "inactive" in stdout_lower or "not running" in stdout_lower:
            firewall_status = "inactive"
            severity = "warning"
        elif "active" in stdout_lower:
            firewall_status = "active"

    return {
        "setting": "Firewall",
        "value": firewall_status,
        "status": "ok" if firewall_status == "active" else "warning",
        "message": "" if firewall_status == "active" else "Firewall is not active",
    }, severity


async def _check_auto_updates(
    ctx: SharedContext,
    host_name: str,
) -> dict[str, Any]:
    """Check for automatic updates (Debian/Ubuntu)."""
    cmd = (
        "dpkg -l unattended-upgrades 2>/dev/null | grep -q '^ii' && "
        "echo 'enabled' || echo 'disabled'"
    )
    result = await execute_security_command(ctx, host_name, cmd, timeout=DEFAULT_TIMEOUT)

    auto_update = result.stdout.strip() == "enabled"
    return {
        "setting": "Automatic Updates",
        "value": "enabled" if auto_update else "disabled",
        "status": "ok" if auto_update else "info",
        "message": "" if auto_update else "Consider enabling automatic security updates",
    }


def _severity_higher(new: str, current: str) -> bool:
    """Check if new severity is higher than current."""
    levels = {"info": 0, "warning": 1, "critical": 2}
    return levels.get(new, 0) > levels.get(current, 0)
