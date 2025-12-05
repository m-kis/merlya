"""
Merlya Tools - Security operations.

Provides tools for security auditing and monitoring on remote hosts.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class SecurityResult:
    """Result of a security operation."""

    success: bool
    data: dict[str, Any] | list[Any] | str | None = None
    error: str | None = None
    severity: str = "info"  # info, warning, critical


@dataclass
class PortInfo:
    """Information about an open port."""

    port: int
    protocol: str
    state: str
    service: str
    pid: int | None = None
    process: str | None = None


@dataclass
class SSHKeyInfo:
    """Information about an SSH key."""

    path: str
    type: str
    bits: int | None = None
    fingerprint: str | None = None
    is_encrypted: bool = False
    permissions: str | None = None
    issues: list[str] = field(default_factory=list)


# Allowed paths for SSH key audit (security: prevent arbitrary file access)
_ALLOWED_SSH_KEY_PATHS = (
    "/home/",
    "/root/",
    "/etc/ssh/",
    "~/.ssh/",
)


def _is_safe_ssh_key_path(path: str) -> bool:
    """Check if path is a valid SSH key location."""
    path = path.strip()
    # Must start with one of the allowed prefixes
    for allowed in _ALLOWED_SSH_KEY_PATHS:
        if path.startswith(allowed):
            return True
    # Also allow paths that look like home directories
    return bool(re.match(r"^/home/[a-zA-Z0-9_-]+/\.ssh/", path))


async def check_open_ports(
    _ctx: SharedContext,
    host_name: str,
    include_listening: bool = True,
    include_established: bool = False,
) -> SecurityResult:
    """
    Check open ports on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        include_listening: Include listening ports.
        include_established: Include established connections.

    Returns:
        SecurityResult with port information.
    """
    from merlya.ssh import SSHPool

    try:
        ssh_pool = await SSHPool.get_instance()

        # Build state filter (validated values only)
        states = []
        if include_listening:
            states.append("listen")
        if include_established:
            states.append("established")

        # ss state filter uses fixed keywords only (no user input)
        state_filter = " or ".join(f"state {s}" for s in states) if states else ""

        # ss command for modern Linux (all fixed strings)
        ss_cmd = f"ss -tulnp {state_filter} 2>/dev/null"
        result = await ssh_pool.execute(host_name, ss_cmd)

        if result.exit_code != 0:
            # Fallback to netstat (fixed command)
            netstat_cmd = "netstat -tulnp 2>/dev/null || netstat -an"
            result = await ssh_pool.execute(host_name, netstat_cmd)

        if result.exit_code != 0:
            return SecurityResult(
                success=False,
                error="Failed to check ports: ss and netstat not available",
            )

        # Parse output
        ports: list[dict[str, Any]] = []
        for line in result.stdout.strip().split("\n")[1:]:  # Skip header
            if not line:
                continue

            # Parse ss output
            parts = line.split()
            if len(parts) >= 5:
                # Extract port from address
                addr = parts[4] if len(parts) > 4 else ""
                port_match = re.search(r":(\d+)$", addr)
                port = int(port_match.group(1)) if port_match else 0

                # Extract process info
                process_info = parts[-1] if parts else ""
                pid_match = re.search(r"pid=(\d+)", process_info)
                pid = int(pid_match.group(1)) if pid_match else None

                proc_match = re.search(r'"([^"]+)"', process_info)
                process = proc_match.group(1) if proc_match else None

                ports.append(
                    {
                        "port": port,
                        "protocol": parts[0].lower() if parts else "unknown",
                        "state": parts[1] if len(parts) > 1 else "unknown",
                        "address": addr,
                        "pid": pid,
                        "process": process,
                    }
                )

        return SecurityResult(success=True, data=ports)

    except Exception as e:
        logger.error(f"Failed to check ports on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def audit_ssh_keys(
    _ctx: SharedContext,
    host_name: str,
) -> SecurityResult:
    """
    Audit SSH keys on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.

    Returns:
        SecurityResult with SSH key audit.
    """
    from merlya.ssh import SSHPool

    try:
        ssh_pool = await SSHPool.get_instance()

        # Find SSH keys (fixed paths only)
        find_cmd = "find ~/.ssh /etc/ssh -type f \\( -name '*.pub' -o -name 'id_*' \\) 2>/dev/null | head -100"
        result = await ssh_pool.execute(host_name, find_cmd)

        keys: list[dict[str, Any]] = []
        severity = "info"

        for key_path in result.stdout.strip().split("\n"):
            if not key_path or key_path.endswith(".pub"):
                continue

            # Security: validate path is in allowed locations
            if not _is_safe_ssh_key_path(key_path):
                logger.warning(f"Skipping suspicious key path: {key_path}")
                continue

            key_info: dict[str, Any] = {"path": key_path, "issues": []}
            quoted_path = shlex.quote(key_path)

            # Check permissions (using quoted path)
            stat_result = await ssh_pool.execute(
                host_name, f"stat -c '%a' {quoted_path} 2>/dev/null"
            )
            if stat_result.exit_code == 0:
                perms = stat_result.stdout.strip()
                key_info["permissions"] = perms
                if perms not in ("600", "400"):
                    key_info["issues"].append(f"Insecure permissions: {perms} (should be 600)")
                    severity = "warning"

            # Check key type and encryption (using quoted path)
            file_result = await ssh_pool.execute(host_name, f"head -1 {quoted_path} 2>/dev/null")
            if file_result.exit_code == 0:
                header = file_result.stdout.strip()
                if "ENCRYPTED" in header:
                    key_info["is_encrypted"] = True
                else:
                    key_info["is_encrypted"] = False
                    key_info["issues"].append("Key is not passphrase protected")
                    severity = "warning"

                if "RSA" in header:
                    key_info["type"] = "RSA"
                elif "EC" in header or "ECDSA" in header:
                    key_info["type"] = "ECDSA"
                elif "ED25519" in header:
                    key_info["type"] = "ED25519"
                elif "DSA" in header:
                    key_info["type"] = "DSA"
                    key_info["issues"].append("DSA keys are deprecated")
                    severity = "critical"
                else:
                    key_info["type"] = "unknown"

            keys.append(key_info)

        return SecurityResult(
            success=True,
            data={"keys": keys, "total": len(keys)},
            severity=severity,
        )

    except Exception as e:
        logger.error(f"Failed to audit SSH keys on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def check_security_config(
    _ctx: SharedContext,
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
    from merlya.ssh import SSHPool

    try:
        ssh_pool = await SSHPool.get_instance()

        checks: list[dict[str, Any]] = []
        severity = "info"

        # Check SSH config (all fixed commands)
        ssh_config_cmd = "grep -E '^(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|PermitEmptyPasswords)' /etc/ssh/sshd_config 2>/dev/null"
        ssh_result = await ssh_pool.execute(host_name, ssh_config_cmd)

        if ssh_result.exit_code == 0:
            for line in ssh_result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    key, value = parts[0], parts[1]
                    status = "ok"
                    message = ""

                    if key == "PermitRootLogin" and value.lower() not in (
                        "no",
                        "prohibit-password",
                    ):
                        status = "warning"
                        message = "Root login should be disabled"
                        severity = "warning"
                    elif key == "PasswordAuthentication" and value.lower() == "yes":
                        status = "warning"
                        message = "Password authentication should be disabled"
                        severity = "warning"
                    elif key == "PermitEmptyPasswords" and value.lower() == "yes":
                        status = "critical"
                        message = "Empty passwords are allowed!"
                        severity = "critical"

                    checks.append(
                        {
                            "setting": key,
                            "value": value,
                            "status": status,
                            "message": message,
                        }
                    )

        # Check firewall status (fixed commands)
        fw_cmd = "command -v ufw >/dev/null && ufw status | head -1 || command -v firewall-cmd >/dev/null && firewall-cmd --state || iptables -L -n 2>/dev/null | head -3"
        fw_result = await ssh_pool.execute(host_name, fw_cmd)

        firewall_status = "unknown"
        if fw_result.stdout and "active" in fw_result.stdout.lower():
            firewall_status = "active"
        elif fw_result.stdout and (
            "inactive" in fw_result.stdout.lower() or "not running" in fw_result.stdout.lower()
        ):
            firewall_status = "inactive"
            severity = "warning" if severity != "critical" else severity

        checks.append(
            {
                "setting": "Firewall",
                "value": firewall_status,
                "status": "ok" if firewall_status == "active" else "warning",
                "message": "" if firewall_status == "active" else "Firewall is not active",
            }
        )

        # Check for unattended upgrades (Debian/Ubuntu) - fixed command
        auto_update_cmd = "dpkg -l unattended-upgrades 2>/dev/null | grep -q '^ii' && echo 'enabled' || echo 'disabled'"
        auto_result = await ssh_pool.execute(host_name, auto_update_cmd)

        auto_update = auto_result.stdout.strip() == "enabled"
        checks.append(
            {
                "setting": "Automatic Updates",
                "value": "enabled" if auto_update else "disabled",
                "status": "ok" if auto_update else "info",
                "message": "" if auto_update else "Consider enabling automatic security updates",
            }
        )

        return SecurityResult(
            success=True,
            data={"checks": checks},
            severity=severity,
        )

    except Exception as e:
        logger.error(f"Failed to check security config on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def check_users(
    _ctx: SharedContext,
    host_name: str,
) -> SecurityResult:
    """
    Audit user accounts on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.

    Returns:
        SecurityResult with user audit.
    """
    from merlya.ssh import SSHPool

    try:
        ssh_pool = await SSHPool.get_instance()

        users: list[dict[str, Any]] = []
        issues: list[str] = []
        severity = "info"

        # Get users with shell access (fixed command)
        passwd_cmd = (
            "grep -E '(/bin/bash|/bin/sh|/bin/zsh|/usr/bin/bash|/usr/bin/zsh)$' /etc/passwd"
        )
        result = await ssh_pool.execute(host_name, passwd_cmd)

        if result.exit_code == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 7:
                    try:
                        uid = int(parts[2])
                        gid = int(parts[3])
                    except ValueError:
                        continue

                    user_info: dict[str, Any] = {
                        "username": parts[0],
                        "uid": uid,
                        "gid": gid,
                        "home": parts[5],
                        "shell": parts[6],
                        "issues": [],
                    }

                    # Check for issues
                    if uid == 0 and parts[0] != "root":
                        user_issues: list[str] = user_info["issues"]
                        user_issues.append("Non-root user with UID 0")
                        severity = "critical"

                    users.append(user_info)

        # Check for users with empty passwords (fixed command, requires sudo)
        shadow_cmd = "sudo cat /etc/shadow 2>/dev/null | grep -E '^[^:]+::'"
        shadow_result = await ssh_pool.execute(host_name, shadow_cmd)

        if shadow_result.exit_code == 0 and shadow_result.stdout.strip():
            for line in shadow_result.stdout.strip().split("\n"):
                if line:
                    username = line.split(":")[0]
                    issues.append(f"User {username} has empty password")
                    severity = "critical"

        return SecurityResult(
            success=True,
            data={"users": users, "issues": issues},
            severity=severity,
        )

    except Exception as e:
        logger.error(f"Failed to audit users on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def check_sudo_config(
    _ctx: SharedContext,
    host_name: str,
) -> SecurityResult:
    """
    Audit sudo configuration on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.

    Returns:
        SecurityResult with sudo audit.
    """
    from merlya.ssh import SSHPool

    try:
        ssh_pool = await SSHPool.get_instance()

        issues: list[str] = []
        severity = "info"

        # Check for NOPASSWD entries (fixed command)
        sudo_cmd = "sudo cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null | grep -v '^#' | grep -v '^$' | grep NOPASSWD"
        result = await ssh_pool.execute(host_name, sudo_cmd)

        nopasswd_entries = []
        if result.exit_code == 0 and result.stdout.strip():
            nopasswd_entries = [
                line.strip() for line in result.stdout.strip().split("\n") if line.strip()
            ]
            if nopasswd_entries:
                issues.append(f"Found {len(nopasswd_entries)} NOPASSWD sudo entries")
                severity = "warning"

        # Check for dangerous sudo permissions (fixed command)
        dangerous_cmd = "sudo cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null | grep -v '^#' | grep -v '^$' | grep -E 'ALL.*ALL.*ALL'"
        dangerous_result = await ssh_pool.execute(host_name, dangerous_cmd)

        dangerous_entries = []
        if dangerous_result.exit_code == 0 and dangerous_result.stdout.strip():
            dangerous_entries = [
                line.strip() for line in dangerous_result.stdout.strip().split("\n") if line.strip()
            ]

        return SecurityResult(
            success=True,
            data={
                "nopasswd_entries": nopasswd_entries,
                "all_access_entries": dangerous_entries,
                "issues": issues,
            },
            severity=severity,
        )

    except Exception as e:
        logger.error(f"Failed to audit sudo on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))
