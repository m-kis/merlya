"""
Merlya Tools - Security SSH key auditing.

Audit SSH keys on remote hosts.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.security.base import (
    DEFAULT_TIMEOUT,
    SecurityResult,
    _is_safe_ssh_key_path,
    execute_security_command,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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
        find_cmd = (
            "find ~/.ssh /etc/ssh -type f "
            "\\( -name '*.pub' -o -name 'id_*' \\) 2>/dev/null | head -100"
        )
        result = await execute_security_command(ctx, host_name, find_cmd, timeout=DEFAULT_TIMEOUT)

        keys: list[dict[str, Any]] = []
        severity = "info"

        for key_path in result.stdout.strip().split("\n"):
            if not key_path or key_path.endswith(".pub"):
                continue

            # Security: validate path is in allowed locations
            if not _is_safe_ssh_key_path(key_path):
                logger.warning(f"⚠️ Skipping suspicious key path: {key_path}")
                continue

            key_info, key_severity = await _audit_single_key(ctx, host_name, key_path)
            keys.append(key_info)
            if _severity_higher(key_severity, severity):
                severity = key_severity

        return SecurityResult(
            success=True,
            data={"keys": keys, "total": len(keys)},
            severity=severity,
        )

    except Exception as e:
        logger.error(f"❌ Failed to audit SSH keys on {host_name}: {e}")
        return SecurityResult(success=False, error=str(e))


async def _audit_single_key(
    ctx: SharedContext,
    host_name: str,
    key_path: str,
) -> tuple[dict[str, Any], str]:
    """Audit a single SSH key file."""
    key_info: dict[str, Any] = {"path": key_path, "issues": []}
    severity = "info"
    quoted_path = shlex.quote(key_path)

    # Check permissions
    stat_result = await execute_security_command(
        ctx, host_name, f"stat -c '%a' {quoted_path} 2>/dev/null", timeout=DEFAULT_TIMEOUT
    )
    if stat_result.exit_code == 0:
        perms = stat_result.stdout.strip()
        key_info["permissions"] = perms
        if perms not in ("600", "400"):
            key_info["issues"].append(f"Insecure permissions: {perms} (should be 600)")
            severity = "warning"

    # Check key type and encryption
    file_result = await execute_security_command(
        ctx, host_name, f"head -1 {quoted_path} 2>/dev/null", timeout=DEFAULT_TIMEOUT
    )
    if file_result.exit_code == 0:
        header = file_result.stdout.strip()
        key_info["is_encrypted"] = "ENCRYPTED" in header
        if not key_info["is_encrypted"]:
            key_info["issues"].append("Key is not passphrase protected")
            severity = "warning"

        key_info["type"] = _detect_key_type(header)
        if key_info["type"] == "DSA":
            key_info["issues"].append("DSA keys are deprecated")
            severity = "critical"

    return key_info, severity


def _detect_key_type(header: str) -> str:
    """Detect SSH key type from header."""
    if "RSA" in header:
        return "RSA"
    elif "EC" in header or "ECDSA" in header:
        return "ECDSA"
    elif "ED25519" in header:
        return "ED25519"
    elif "DSA" in header:
        return "DSA"
    return "unknown"


def _severity_higher(new: str, current: str) -> bool:
    """Check if new severity is higher than current."""
    levels = {"info": 0, "warning": 1, "critical": 2}
    return levels.get(new, 0) > levels.get(current, 0)
