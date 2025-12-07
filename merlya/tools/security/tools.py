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

from merlya.ssh.pool import SSHConnectionOptions, SSHResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


DEFAULT_TIMEOUT = 20


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


async def _execute_command(
    ctx: "SharedContext",
    host_name: str,
    command: str,
    timeout: int = 60,
    connect_timeout: int | None = None,
) -> SSHResult:
    """Execute a command on a host using shared SSH pool and inventory resolution."""
    host_entry = await ctx.hosts.get_by_name(host_name)
    ssh_pool = await ctx.get_ssh_pool()

    target = host_name
    username: str | None = None
    private_key: str | None = None
    options = SSHConnectionOptions(connect_timeout=connect_timeout or 15)

    if host_entry:
        target = host_entry.hostname
        username = host_entry.username
        private_key = host_entry.private_key
        options = SSHConnectionOptions(
            port=host_entry.port,
            jump_host=host_entry.jump_host,
            connect_timeout=connect_timeout or 15,
        )

    return await ssh_pool.execute(
        host=target,
        command=command,
        timeout=timeout,
        username=username,
        private_key=private_key,
        options=options,
        host_name=host_name,  # Pass inventory name for credential lookup
    )


async def check_open_ports(
    ctx: SharedContext,
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
    try:
        # Build state filter (validated values only)
        states = []
        if include_listening:
            states.append("listen")
        if include_established:
            states.append("established")

        # ss state filter uses fixed keywords only (no user input)
        state_filter = " ".join(f"state {s}" for s in states) if states else ""

        # ss command for modern Linux (all fixed strings, numeric, headerless)
        ss_cmd = f"ss -tulnHp {state_filter} 2>/dev/null".strip()
        result = await _execute_command(ctx, host_name, ss_cmd, timeout=DEFAULT_TIMEOUT)

        if result.exit_code != 0:
            # Fallback to netstat (fixed command)
            netstat_cmd = "netstat -tuln 2>/dev/null || netstat -an"
            result = await _execute_command(ctx, host_name, netstat_cmd, timeout=DEFAULT_TIMEOUT)

        if result.exit_code != 0:
            return SecurityResult(
                success=False,
                error="Failed to check ports: ss and netstat not available",
            )

        # Parse output (ss -H or netstat)
        ports: list[dict[str, Any]] = []
        ss_pattern = re.compile(
            r"^(?P<proto>\S+)\s+(?P<state>\S+)\s+\S+\s+\S+\s+(?P<local>\S+)\s+(?P<peer>\S+)\s*(?P<proc>.*)"
        )

        def _extract_port(address: str) -> int | str | None:
            if ":" in address:
                label = address.rsplit(":", 1)[-1]
            else:
                label = address
            label = label.strip("[]")
            if not label or label == "*":
                return None
            try:
                return int(label)
            except (TypeError, ValueError):
                return label

        def _extract_process(proc_str: str) -> tuple[int | None, str | None]:
            pid = None
            process = None
            pid_match = re.search(r"pid=(\d+)", proc_str)
            if pid_match:
                pid = int(pid_match.group(1))
            quoted = re.search(r'"([^"]+)"', proc_str)
            if quoted:
                process = quoted.group(1)
            else:
                slash_match = re.search(r"(\d+)/([^\s]+)", proc_str)
                if slash_match:
                    pid = pid or int(slash_match.group(1))
                    process = slash_match.group(2)
            return pid, process

        def _add_port_entry(
            port_value: int | str,
            protocol: str,
            state: str,
            address: str,
            pid: int | None,
            process: str | None,
        ) -> None:
            service = (
                port_value if isinstance(port_value, str) and not port_value.isdigit() else None
            )
            ports.append(
                {
                    "port": port_value,
                    "protocol": protocol,
                    "state": state.lower() if isinstance(state, str) else "unknown",
                    "address": address,
                    "service": service,
                    "pid": pid,
                    "process": process,
                }
            )

        for line in result.stdout.strip().splitlines():
            if (
                not line
                or line.startswith(("Netid", "Proto", "Active", "Recv-Q"))
                or "Local Address" in line
                or "Local" in line and "Foreign" in line
            ):
                continue

            match = ss_pattern.match(line)
            if match:
                proto = match.group("proto").split("/")[0].lower()
                state = match.group("state")
                local_addr = match.group("local")
                port_value = _extract_port(local_addr)
                if port_value is None:
                    continue
                pid, process = _extract_process(match.group("proc") or "")
                _add_port_entry(port_value, proto, state, local_addr, pid, process)
                continue

            parts = line.split()
            if len(parts) >= 4:
                proto = parts[0].lower()
                local_addr = parts[3]
                state = parts[5] if len(parts) > 5 else (parts[1] if len(parts) > 1 else "unknown")
                port_value = _extract_port(local_addr)
                if port_value is None:
                    continue
                pid, process = _extract_process(" ".join(parts[6:]) if len(parts) > 6 else "")
                _add_port_entry(port_value, proto, state, local_addr, pid, process)

        return SecurityResult(success=True, data=ports)

    except Exception as e:
        logger.error(f"Failed to check ports on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def audit_ssh_keys(
    ctx: SharedContext,
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
    try:
        # Find SSH keys (fixed paths only)
        find_cmd = "find ~/.ssh /etc/ssh -type f \\( -name '*.pub' -o -name 'id_*' \\) 2>/dev/null | head -100"
        result = await _execute_command(ctx, host_name, find_cmd, timeout=DEFAULT_TIMEOUT)

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
            stat_result = await _execute_command(
                ctx, host_name, f"stat -c '%a' {quoted_path} 2>/dev/null", timeout=DEFAULT_TIMEOUT
            )
            if stat_result.exit_code == 0:
                perms = stat_result.stdout.strip()
                key_info["permissions"] = perms
                if perms not in ("600", "400"):
                    key_info["issues"].append(f"Insecure permissions: {perms} (should be 600)")
                    severity = "warning"

            # Check key type and encryption (using quoted path)
            file_result = await _execute_command(
                ctx, host_name, f"head -1 {quoted_path} 2>/dev/null", timeout=DEFAULT_TIMEOUT
            )
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

        # Check SSH config (all fixed commands)
        ssh_config_cmd = "grep -E '^(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|PermitEmptyPasswords)' /etc/ssh/sshd_config 2>/dev/null"
        ssh_result = await _execute_command(ctx, host_name, ssh_config_cmd, timeout=DEFAULT_TIMEOUT)

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
        fw_result = await _execute_command(ctx, host_name, fw_cmd, timeout=DEFAULT_TIMEOUT)

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
        auto_result = await _execute_command(ctx, host_name, auto_update_cmd, timeout=DEFAULT_TIMEOUT)

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
    ctx: SharedContext,
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
    try:
        users: list[dict[str, Any]] = []
        issues: list[str] = []
        severity = "info"

        # Get users with shell access (fixed command)
        passwd_cmd = (
            "grep -E '(/bin/bash|/bin/sh|/bin/zsh|/usr/bin/bash|/usr/bin/zsh)$' /etc/passwd"
        )
        result = await _execute_command(ctx, host_name, passwd_cmd, timeout=DEFAULT_TIMEOUT)

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
        shadow_result = await _execute_command(ctx, host_name, shadow_cmd, timeout=DEFAULT_TIMEOUT)

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
    ctx: SharedContext,
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
    try:
        issues: list[str] = []
        severity = "info"

        # Check for NOPASSWD entries (fixed command)
        sudo_cmd = "sudo cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null | grep -v '^#' | grep -v '^$' | grep NOPASSWD"
        result = await _execute_command(ctx, host_name, sudo_cmd, timeout=DEFAULT_TIMEOUT)

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
        dangerous_result = await _execute_command(ctx, host_name, dangerous_cmd, timeout=DEFAULT_TIMEOUT)

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

        # Check auth.log or secure log (fixed command)
        cmd = f"""
        {{ journalctl -u sshd --since '{hours} hours ago' 2>/dev/null || cat /var/log/auth.log 2>/dev/null || cat /var/log/secure 2>/dev/null; }} | \
        grep -iE '(failed|invalid|refused)' | \
        grep -v 'Disconnected from' | \
        tail -100
        """
        result = await _execute_command(ctx, host_name, cmd.strip(), timeout=DEFAULT_TIMEOUT)

        failed_attempts: list[dict[str, Any]] = []
        severity = "info"
        ip_counts: dict[str, int] = {}

        if result.exit_code == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # Extract IP addresses from log lines
                ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                if ip_match:
                    ip = ip_match.group(1)
                    ip_counts[ip] = ip_counts.get(ip, 0) + 1

                failed_attempts.append({"line": line[:200]})  # Truncate long lines

        # Determine severity based on attempt count
        total_attempts = len(failed_attempts)
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
        logger.error(f"Failed to check failed logins on {host_name}: {type(e).__name__}: {e}")
        return SecurityResult(success=False, error=str(e))


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
        # Combined command that tries each package manager
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

        result = await _execute_command(ctx, host_name, cmd.strip(), timeout=30)

        updates: list[dict[str, str]] = []
        pkg_manager = "unknown"
        severity = "info"

        if result.stdout:
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if line.startswith("PKG_MANAGER:"):
                    pkg_manager = line.split(":", 1)[1]
                elif line and not line.startswith("Last metadata"):
                    # Parse package name
                    parts = line.split()
                    if parts:
                        pkg_name = parts[0].split("/")[0]  # Remove arch/repo info
                        is_security = "security" in line.lower()
                        updates.append({
                            "package": pkg_name,
                            "security": is_security,
                        })

        # Security updates count
        security_updates = [u for u in updates if u.get("security")]

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
                "packages": updates[:20],  # Limit output
            },
            severity=severity,
        )

    except Exception as e:
        logger.error(f"Failed to check updates on {host_name}: {type(e).__name__}: {e}")
        return SecurityResult(success=False, error=str(e))


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
        safe_services = [
            s for s in services_to_check
            if re.match(r"^[a-zA-Z0-9_.-]+$", s)
        ][:20]  # Limit to 20 services

        if not safe_services:
            return SecurityResult(success=False, error="No valid service names provided")

        # Build command to check all services
        service_checks = " ".join(
            f"systemctl is-active {shlex.quote(s)} 2>/dev/null || echo inactive"
            for s in safe_services
        )
        names_echo = " ".join(safe_services)

        cmd = f"""
        echo "SERVICES:{names_echo}"
        for svc in {names_echo}; do
            status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
            echo "$svc:$status"
        done
        """

        result = await _execute_command(ctx, host_name, cmd.strip(), timeout=DEFAULT_TIMEOUT)

        service_status: list[dict[str, Any]] = []
        severity = "info"
        inactive_count = 0

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if ":" in line and not line.startswith("SERVICES:"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        svc_name, status = parts
                        is_active = status.strip() == "active"
                        service_status.append({
                            "service": svc_name.strip(),
                            "status": status.strip(),
                            "active": is_active,
                        })
                        if not is_active and status.strip() != "not-found":
                            inactive_count += 1

        # Severity based on inactive critical services
        if inactive_count > 0:
            # Check if sshd or firewall is down
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
        logger.error(f"Failed to check services on {host_name}: {type(e).__name__}: {e}")
        return SecurityResult(success=False, error=str(e))
