"""
Merlya Tools - Security user auditing.

Audit user accounts and sudo configuration on remote hosts.
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
        result = await execute_security_command(ctx, host_name, passwd_cmd, timeout=DEFAULT_TIMEOUT)

        if result.exit_code == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                user_info, user_severity = _parse_passwd_line(line)
                if user_info:
                    users.append(user_info)
                    if user_severity == "critical":
                        severity = "critical"

        # Check for users with empty passwords
        empty_pwd_issues, empty_pwd_severity = await _check_empty_passwords(ctx, host_name)
        issues.extend(empty_pwd_issues)
        if empty_pwd_severity == "critical":
            severity = "critical"

        return SecurityResult(
            success=True,
            data={"users": users, "issues": issues},
            severity=severity,
        )

    except Exception as e:
        logger.error(f"❌ Failed to audit users on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


def _parse_passwd_line(line: str) -> tuple[dict[str, Any] | None, str]:
    """Parse /etc/passwd line into user info."""
    parts = line.split(":")
    if len(parts) < 7:
        return None, "info"

    try:
        uid = int(parts[2])
        gid = int(parts[3])
    except ValueError:
        return None, "info"

    user_info: dict[str, Any] = {
        "username": parts[0],
        "uid": uid,
        "gid": gid,
        "home": parts[5],
        "shell": parts[6],
        "issues": [],
    }

    severity = "info"
    if uid == 0 and parts[0] != "root":
        user_info["issues"].append("Non-root user with UID 0")
        severity = "critical"

    return user_info, severity


async def _check_empty_passwords(
    ctx: SharedContext,
    host_name: str,
) -> tuple[list[str], str]:
    """Check for users with empty passwords."""
    issues: list[str] = []
    severity = "info"

    shadow_cmd = "sudo cat /etc/shadow 2>/dev/null | grep -E '^[^:]+::'"
    result = await execute_security_command(ctx, host_name, shadow_cmd, timeout=DEFAULT_TIMEOUT)

    if result.exit_code == 0 and result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            if line:
                username = line.split(":")[0]
                issues.append(f"User {username} has empty password")
                severity = "critical"

    return issues, severity


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

        # Check for NOPASSWD entries
        nopasswd_entries, nopasswd_severity = await _check_nopasswd(ctx, host_name)
        if nopasswd_entries:
            issues.append(f"Found {len(nopasswd_entries)} NOPASSWD sudo entries")
            severity = nopasswd_severity

        # Check for dangerous sudo permissions
        dangerous_entries = await _check_dangerous_sudo(ctx, host_name)

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
        logger.error(f"❌ Failed to audit sudo on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def _check_nopasswd(
    ctx: SharedContext,
    host_name: str,
) -> tuple[list[str], str]:
    """Check for NOPASSWD sudo entries."""
    cmd = (
        "sudo cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null | "
        "grep -v '^#' | grep -v '^$' | grep NOPASSWD"
    )
    result = await execute_security_command(ctx, host_name, cmd, timeout=DEFAULT_TIMEOUT)

    entries: list[str] = []
    severity = "info"

    if result.exit_code == 0 and result.stdout.strip():
        entries = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        if entries:
            severity = "warning"

    return entries, severity


async def _check_dangerous_sudo(
    ctx: SharedContext,
    host_name: str,
) -> list[str]:
    """Check for dangerous (ALL) sudo permissions."""
    cmd = (
        "sudo cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null | "
        "grep -v '^#' | grep -v '^$' | grep -E 'ALL.*ALL.*ALL'"
    )
    result = await execute_security_command(ctx, host_name, cmd, timeout=DEFAULT_TIMEOUT)

    if result.exit_code == 0 and result.stdout.strip():
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]

    return []
