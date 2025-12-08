"""
Merlya Tools - Security monitoring.

Monitor failed logins, pending updates, and critical services on remote hosts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.security.base import (
    DEFAULT_TIMEOUT,
    SecurityResult,
    execute_security_command,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def check_failed_logins(
    ctx: SharedContext,
    host_name: str,
    hours: int = 24,
) -> SecurityResult:
    """
    Check for failed login attempts in the last N hours.

    Args:
        ctx: Shared context.
        host_name: Host name.
        hours: Number of hours to look back (default 24).

    Returns:
        SecurityResult with failed login information.
    """
    try:
        # Clamp hours to reasonable range
        hours = max(1, min(hours, 168))  # 1 hour to 1 week

        cmd = f"""
        {{ journalctl -u sshd --since '{hours} hours ago' 2>/dev/null || \
           cat /var/log/auth.log 2>/dev/null || \
           cat /var/log/secure 2>/dev/null; }} | \
        grep -iE '(failed|invalid|refused)' | \
        grep -v 'Disconnected from' | \
        tail -100
        """
        result = await execute_security_command(
            ctx, host_name, cmd.strip(), timeout=DEFAULT_TIMEOUT
        )

        failed_attempts, ip_counts = _parse_failed_logins(result.stdout)

        # Determine severity
        total_attempts = len(failed_attempts)
        severity = "info"
        if total_attempts > 50:
            severity = "critical"
        elif total_attempts > 20:
            severity = "warning"

        # Top offending IPs
        top_ips = sorted(ip_counts.items(), key=lambda x: -x[1])[:10]

        return SecurityResult(
            success=True,
            data={
                "total_attempts": total_attempts,
                "top_ips": [{"ip": ip, "count": count} for ip, count in top_ips],
                "hours_checked": hours,
            },
            severity=severity,
        )

    except Exception as e:
        logger.error(f"❌ Failed to check failed logins on {host_name}: {type(e).__name__}: {e}")
        return SecurityResult(success=False, error=str(e))


def _parse_failed_logins(stdout: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse failed login log output."""
    failed_attempts: list[dict[str, Any]] = []
    ip_counts: dict[str, int] = {}

    if not stdout.strip():
        return failed_attempts, ip_counts

    for line in stdout.strip().split("\n"):
        if not line:
            continue
        # Extract IP addresses
        ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
        if ip_match:
            ip = ip_match.group(1)
            ip_counts[ip] = ip_counts.get(ip, 0) + 1

        failed_attempts.append({"line": line[:200]})  # Truncate long lines

    return failed_attempts, ip_counts


async def check_pending_updates(
    ctx: SharedContext,
    host_name: str,
) -> SecurityResult:
    """
    Check for pending security updates.

    Args:
        ctx: Shared context.
        host_name: Host name.

    Returns:
        SecurityResult with pending updates information.
    """
    try:
        cmd = """
        if command -v apt >/dev/null 2>&1; then
            echo "PKG_MANAGER:apt"
            apt list --upgradable 2>/dev/null | grep -v 'Listing' | head -30
        elif command -v dnf >/dev/null 2>&1; then
            echo "PKG_MANAGER:dnf"
            dnf check-update 2>/dev/null | grep -E '^[a-zA-Z0-9]' | head -30
        elif command -v yum >/dev/null 2>&1; then
            echo "PKG_MANAGER:yum"
            yum check-update 2>/dev/null | grep -E '^[a-zA-Z0-9]' | head -30
        else
            echo "PKG_MANAGER:unknown"
        fi
        """
        result = await execute_security_command(ctx, host_name, cmd.strip(), timeout=30)

        updates, pkg_manager = _parse_updates(result.stdout)
        security_updates = [u for u in updates if u.get("security")]

        # Determine severity
        severity = "info"
        if len(security_updates) > 5:
            severity = "critical"
        elif len(updates) > 10:
            severity = "warning"

        return SecurityResult(
            success=True,
            data={
                "package_manager": pkg_manager,
                "total_updates": len(updates),
                "security_updates": len(security_updates),
                "packages": updates[:20],
            },
            severity=severity,
        )

    except Exception as e:
        logger.error(f"❌ Failed to check updates on {host_name}: {type(e).__name__}: {e}")
        return SecurityResult(success=False, error=str(e))


def _parse_updates(stdout: str) -> tuple[list[dict[str, str]], str]:
    """Parse package update output."""
    updates: list[dict[str, str]] = []
    pkg_manager = "unknown"

    if not stdout:
        return updates, pkg_manager

    for line in stdout.strip().split("\n"):
        if line.startswith("PKG_MANAGER:"):
            pkg_manager = line.split(":", 1)[1]
        elif line and not line.startswith("Last metadata"):
            parts = line.split()
            if parts:
                pkg_name = parts[0].split("/")[0]
                is_security = "security" in line.lower()
                updates.append(
                    {
                        "package": pkg_name,
                        "security": is_security,  # type: ignore[dict-item]
                    }
                )

    return updates, pkg_manager


async def check_critical_services(
    ctx: SharedContext,
    host_name: str,
    services: list[str] | None = None,
) -> SecurityResult:
    """
    Check status of critical services.

    Args:
        ctx: Shared context.
        host_name: Host name.
        services: List of services to check. Defaults to security-related services.

    Returns:
        SecurityResult with service status.
    """
    try:
        # Default critical services
        default_services = ["sshd", "fail2ban", "ufw", "firewalld", "auditd"]
        services_to_check = services or default_services

        # Validate service names (alphanumeric, dash, underscore, dot only)
        safe_services = [s for s in services_to_check if re.match(r"^[a-zA-Z0-9_.-]+$", s)][
            :20
        ]  # Limit to 20 services

        if not safe_services:
            return SecurityResult(success=False, error="No valid service names provided")

        names_echo = " ".join(safe_services)
        cmd = f"""
        echo "SERVICES:{names_echo}"
        for svc in {names_echo}; do
            status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
            echo "$svc:$status"
        done
        """
        result = await execute_security_command(
            ctx, host_name, cmd.strip(), timeout=DEFAULT_TIMEOUT
        )

        service_status, inactive_count = _parse_services(result.stdout)

        # Determine severity
        severity = "info"
        if inactive_count > 0:
            critical_down = any(
                s["service"] in ("sshd", "fail2ban", "ufw", "firewalld")
                and not s["active"]
                and s["status"] != "not-found"
                for s in service_status
            )
            severity = "critical" if critical_down else "warning"

        return SecurityResult(
            success=True,
            data={
                "services": service_status,
                "active_count": sum(1 for s in service_status if s["active"]),
                "inactive_count": inactive_count,
            },
            severity=severity,
        )

    except Exception as e:
        logger.error(f"❌ Failed to check services on {host_name}: {type(e).__name__}: {e}")
        return SecurityResult(success=False, error=str(e))


def _parse_services(stdout: str) -> tuple[list[dict[str, Any]], int]:
    """Parse service status output."""
    service_status: list[dict[str, Any]] = []
    inactive_count = 0

    if not stdout:
        return service_status, inactive_count

    for line in stdout.strip().split("\n"):
        if ":" in line and not line.startswith("SERVICES:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                svc_name, status = parts
                is_active = status.strip() == "active"
                service_status.append(
                    {
                        "service": svc_name.strip(),
                        "status": status.strip(),
                        "active": is_active,
                    }
                )
                if not is_active and status.strip() != "not-found":
                    inactive_count += 1

    return service_status, inactive_count
