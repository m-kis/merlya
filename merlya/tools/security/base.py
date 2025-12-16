"""
Merlya Tools - Security base types and helpers.

Common types and utilities for security tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
    """Check if path is a valid SSH key location.

    Uses path normalization to prevent path traversal attacks.
    Only absolute paths that resolve to allowed directories are accepted.
    """
    import posixpath

    path = path.strip()

    # Handle tilde expansion for ~ paths
    if path.startswith("~"):
        # For ~ paths, we check the pattern without resolving
        # since we can't resolve ~ on remote systems
        return path.startswith("~/.ssh/")

    # SECURITY: Reject relative paths - SSH key paths must be absolute
    # This prevents path traversal attacks like "../etc/passwd" which could
    # resolve to allowed locations depending on CWD (e.g., /home/runner/../etc/passwd)
    if not path.startswith("/"):
        return False

    # Normalize the path to eliminate .. segments
    # Using posixpath.normpath for consistent cross-platform behavior
    # (these paths are for remote Linux systems)
    normalized = posixpath.normpath(path)

    # Check if normalized path starts with an allowed prefix
    for allowed in _ALLOWED_SSH_KEY_PATHS:
        if allowed.startswith("~"):
            continue  # Skip ~ prefixes, handled above
        if normalized.startswith(allowed):
            return True

    # Also allow paths that look like home directories (after normalization)
    return bool(re.match(r"^/home/[a-zA-Z0-9_-]+/\.ssh/", normalized))


async def execute_security_command(
    ctx: SharedContext,
    host_name: str,
    command: str,
    timeout: int = 60,
    connect_timeout: int | None = None,
    input_data: str | None = None,
) -> SSHResult:
    """
    Execute a command on a host using shared SSH pool and inventory resolution.

    Args:
        ctx: Shared context.
        host_name: Host name from inventory or raw hostname.
        command: Command to execute.
        timeout: Command timeout in seconds.
        connect_timeout: Connection timeout in seconds.
        input_data: Optional stdin data.

    Returns:
        SSHResult with stdout, stderr, and exit_code.
    """
    # Normalize host name (strip @ prefix if present)
    if host_name.startswith("@"):
        host_name = host_name[1:]

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
        input_data=input_data,
        username=username,
        private_key=private_key,
        options=options,
        host_name=host_name,
    )
