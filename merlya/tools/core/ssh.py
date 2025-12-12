"""
Merlya Tools - SSH execution.

Execute commands on remote hosts via SSH.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.resolve import (
    get_resolved_host_names,
    resolve_host_references,
    resolve_secrets,
)
from merlya.tools.core.security import detect_unsafe_password

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.ssh import SSHConnectionOptions, SSHPool


# =============================================================================
# Helper Functions
# =============================================================================


def _is_ip(value: str) -> bool:
    """Return True if value is a valid IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _explain_ssh_error(error: Exception, host: str, via: str | None = None) -> dict[str, str]:
    """
    Parse SSH error and return human-readable explanation with suggested solutions.

    Returns dict with keys:
    - symptom: What happened (technical)
    - explanation: Why it happened (human-readable)
    - suggestion: What to do about it
    """
    error_str = str(error).lower()
    error_full = str(error)

    # Connection timeout (Errno 60 on macOS, 110 on Linux)
    if "errno 60" in error_str or "errno 110" in error_str or "timed out" in error_str:
        target = via if via else host
        return {
            "symptom": f"Connection timeout to {target}",
            "explanation": f"Could not establish TCP connection to {target}:22 within timeout",
            "suggestion": (
                f"Check: (1) VPN connected? (2) {target} reachable? (3) Port 22 open? "
                f"Try: ping {target} or nc -zv {target} 22"
            ),
        }

    # Connection refused (port closed or service down)
    if "connection refused" in error_str or "errno 111" in error_str:
        target = via if via else host
        return {
            "symptom": f"Connection refused by {target}",
            "explanation": "TCP connection was actively refused (SSH service not running or port blocked)",
            "suggestion": f"Check if SSH service is running on {target}: systemctl status sshd",
        }

    # Host unreachable
    if "no route to host" in error_str or "network is unreachable" in error_str:
        target = via if via else host
        return {
            "symptom": f"No route to host {target}",
            "explanation": "Network path to host does not exist (routing issue)",
            "suggestion": "Check: (1) VPN connected? (2) Network configuration (3) Firewall rules",
        }

    # DNS resolution failure
    if "name or service not known" in error_str or "nodename nor servname provided" in error_str:
        return {
            "symptom": f"DNS resolution failed for {host}",
            "explanation": "Could not resolve hostname to IP address",
            "suggestion": "Check: (1) Hostname spelling (2) DNS configuration (3) /etc/hosts",
        }

    # Authentication failure
    if "authentication failed" in error_str or "permission denied" in error_str:
        return {
            "symptom": f"Authentication failed for {host}",
            "explanation": "SSH key or password rejected by server",
            "suggestion": "Check: (1) SSH key exists and loaded (ssh-add -l) (2) Key authorized on server (3) Username correct",
        }

    # Host key verification
    if "host key verification failed" in error_str:
        return {
            "symptom": f"Host key verification failed for {host}",
            "explanation": "Server's SSH key doesn't match known_hosts (possible MITM or server reinstall)",
            "suggestion": f"If expected: ssh-keygen -R {host} then reconnect to accept new key",
        }

    # Generic fallback
    return {
        "symptom": error_full,
        "explanation": "SSH connection or execution error",
        "suggestion": "Check SSH connectivity manually: ssh <user>@<host>",
    }


def _ensure_callbacks(ctx: SharedContext, ssh_pool: SSHPool) -> None:
    """
    Ensure MFA and passphrase callbacks are set for SSH operations.

    Uses blocking prompts in background threads to avoid event-loop conflicts.
    """
    import asyncio as _asyncio
    import concurrent.futures

    if hasattr(ssh_pool, "has_passphrase_callback") and not ssh_pool.has_passphrase_callback():

        def passphrase_cb(key_path: str) -> str:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 Passphrase for {key_path}"))
                )
                return future.result(timeout=60)

        ssh_pool.set_passphrase_callback(passphrase_cb)

    if hasattr(ssh_pool, "has_mfa_callback") and not ssh_pool.has_mfa_callback():

        def mfa_cb(prompt: str) -> str:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 {prompt}")))
                return future.result(timeout=120)

        ssh_pool.set_mfa_callback(mfa_cb)


@dataclass
class JumpHostConfig:
    """Jump host configuration for SSH tunneling."""

    host: str
    port: int | None = None
    username: str | None = None
    private_key: str | None = None


async def _resolve_jump_host(
    ctx: SharedContext,
    jump_host_name: str,
) -> JumpHostConfig:
    """
    Resolve jump host configuration from inventory or use directly.

    Args:
        ctx: Shared context.
        jump_host_name: Jump host name (inventory entry or hostname/IP).

    Returns:
        JumpHostConfig with resolved configuration.
    """
    try:
        jump_entry = await ctx.hosts.get_by_name(jump_host_name)
    except Exception:
        jump_entry = None

    if jump_entry:
        logger.debug(f"🔗 Using jump host '{jump_host_name}' ({jump_entry.hostname})")
        return JumpHostConfig(
            host=jump_entry.hostname,
            port=jump_entry.port,
            username=jump_entry.username,
            private_key=jump_entry.private_key,
        )
    else:
        # Use jump_host_name directly as hostname if not in inventory
        logger.debug(f"🔗 Using jump host '{jump_host_name}' (direct)")
        return JumpHostConfig(host=jump_host_name)


async def _handle_auto_elevation(
    ctx: SharedContext,
    host: str,
    base_command: str,
) -> tuple[str, str | None, str | None]:
    """
    Handle automatic elevation retry on permission errors.

    Args:
        ctx: Shared context.
        host: Target host name.
        base_command: Original command without elevation.

    Returns:
        Tuple of (elevated_command, input_data, method) or (base_command, None, None) if no elevation.
    """
    permissions = await ctx.get_permissions()
    elevation_result = await permissions.prepare_command(host, base_command)  # type: ignore[attr-defined]

    if not elevation_result.method:
        return base_command, None, None

    elevated_cmd = elevation_result.command
    elevated_input = elevation_result.input_data
    method = elevation_result.method

    # Get cached capabilities for elevate_command calls
    capabilities = await permissions.detect_capabilities(host)  # type: ignore[attr-defined]

    # If elevation needs password and we don't have input, prompt
    if elevation_result.needs_password and not elevated_input:
        password = await ctx.ui.prompt_secret("🔑 Elevation password required")
        if password:
            # Cache password for reuse in this session
            permissions.cache_password(host, password)  # type: ignore[attr-defined]
            elevated_cmd, elevated_input = permissions.elevate_command(  # type: ignore[attr-defined]
                base_command, capabilities, method, password
            )

    return elevated_cmd, elevated_input, method


async def _retry_with_password(
    ctx: SharedContext,
    host: str,
    base_command: str,
    method: str,
    result: Any,
) -> tuple[str, str | None] | None:
    """
    Retry elevation with password if authentication failed.

    Args:
        ctx: Shared context.
        host: Target host name.
        base_command: Original command without elevation.
        method: Elevation method (su, sudo_with_password).
        result: SSH execution result.

    Returns:
        Tuple of (elevated_command, input_data) or None if no retry needed.
    """
    auth_errors = (
        "authentication failure",
        "sorry",
        "incorrect password",
        "permission denied",
        "must be run from a terminal",
    )

    if not any(err in result.stderr.lower() for err in auth_errors):
        return None

    if method not in ("su", "sudo_with_password"):
        return None

    logger.debug(f"🔒 {method} requires password, prompting user...")
    password = await ctx.ui.prompt_secret(f"🔑 {method} password required")

    if not password:
        return None

    permissions = await ctx.get_permissions()
    permissions.cache_password(host, password)  # type: ignore[attr-defined]
    capabilities = await permissions.detect_capabilities(host)  # type: ignore[attr-defined]

    elevated_cmd, elevated_input = permissions.elevate_command(  # type: ignore[attr-defined]
        base_command, capabilities, method, password
    )
    return elevated_cmd, elevated_input


# =============================================================================
# Main SSH Execute Function
# =============================================================================


async def ssh_execute(
    ctx: SharedContext,
    host: str,
    command: str,
    timeout: int = 60,
    connect_timeout: int | None = None,
    elevation: dict[str, Any] | None = None,
    via: str | None = None,
    auto_elevate: bool = True,
) -> ToolResult:
    """
    Execute a command on a host via SSH.

    Features:
    - Secret resolution: @secret-name in commands are resolved from keyring
    - Auto-elevation: Permission denied errors trigger automatic elevation retry

    Args:
        ctx: Shared context.
        host: Host name or hostname.
        command: Command to execute. Can contain @secret-name references.
        timeout: Command timeout in seconds.
        connect_timeout: Optional connection timeout.
        elevation: Optional prepared elevation payload (from request_elevation).
        via: Optional jump host/bastion to use for this connection.
        auto_elevate: If True, automatically retry with elevation on permission errors.

    Returns:
        ToolResult with command output.
    """
    safe_command = command  # Initialize early for exception handling

    try:
        # SECURITY: Check for plaintext passwords in command
        unsafe_warning = detect_unsafe_password(command)
        if unsafe_warning:
            logger.warning(unsafe_warning)
            return ToolResult(
                success=False,
                error=unsafe_warning,
                data={"host": host, "command": command[:50] + "..."},
            )

        # Get hosts for reference resolution
        all_hosts = await ctx.hosts.get_all()

        # 1. Resolve @hostname references → actual hostnames/IPs
        resolved_command = await resolve_host_references(command, all_hosts, ctx.ui)

        # Track which host names were resolved (to skip in secret resolution)
        resolved_host_names = get_resolved_host_names(all_hosts)

        # 2. Resolve @secret references → actual values
        resolved_command, safe_command = resolve_secrets(
            resolved_command, ctx.secrets, resolved_host_names
        )

        # Resolve host from inventory (optional - inventory is a convenience)
        host_entry: Host | None = await ctx.hosts.get_by_name(host)

        if not host_entry:
            if _is_ip(host):
                logger.debug(f"Using direct IP (no inventory) for SSH: {host}")
            else:
                logger.debug(f"Host '{host}' not in inventory, attempting direct connection")

        # Build SSH connection options
        from merlya.ssh import SSHConnectionOptions

        ssh_opts = SSHConnectionOptions(connect_timeout=connect_timeout)

        # Resolve jump host - 'via' parameter takes priority over inventory config
        jump_host_name = via or (host_entry.jump_host if host_entry else None)

        if jump_host_name:
            jump_config = await _resolve_jump_host(ctx, jump_host_name)
            ssh_opts.jump_host = jump_config.host
            ssh_opts.jump_port = jump_config.port
            ssh_opts.jump_username = jump_config.username
            ssh_opts.jump_private_key = jump_config.private_key

        # Apply prepared elevation (brain-driven only)
        input_data = None
        elevation_used = None
        base_command = resolved_command

        if elevation:
            resolved_command = elevation.get("command", resolved_command)
            base_command = elevation.get("base_command", resolved_command)
            input_data = elevation.get("input")
            elevation_used = elevation.get("method")

        # Get SSH pool and ensure callbacks
        ssh_pool = await ctx.get_ssh_pool()
        _ensure_callbacks(ctx, ssh_pool)

        # Execute SSH command
        result = await _execute_ssh(
            ssh_pool, host, host_entry, resolved_command, timeout, input_data, ssh_opts
        )

        # Auto-elevation: retry with elevation on permission errors
        permission_errors = ("permission denied", "operation not permitted", "access denied")
        needs_elevation = (
            result.exit_code != 0
            and not elevation_used
            and auto_elevate
            and any(err in result.stderr.lower() for err in permission_errors)
        )

        if needs_elevation:
            logger.info(f"🔒 Permission denied on {host}, attempting elevation...")
            result, elevation_used = await _execute_with_elevation(
                ctx, ssh_pool, host, host_entry, base_command, timeout, ssh_opts, result
            )

        return ToolResult(
            success=result.exit_code == 0,
            data={
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "host": host,
                "command": safe_command[:50] + "..." if len(safe_command) > 50 else safe_command,
                "elevation": elevation_used,
                "via": jump_host_name,
            },
            error=result.stderr if result.exit_code != 0 else None,
        )

    except Exception as e:
        error_info = _explain_ssh_error(e, host, via=via)
        logger.error(f"SSH execution failed: {error_info['symptom']}")
        logger.info(f"💡 {error_info['suggestion']}")

        return ToolResult(
            success=False,
            data={
                "host": host,
                "command": safe_command[:50],
                "symptom": error_info["symptom"],
                "explanation": error_info["explanation"],
                "suggestion": error_info["suggestion"],
            },
            error=f"{error_info['symptom']} - {error_info['explanation']}",
        )


async def _execute_ssh(
    ssh_pool: SSHPool,
    host: str,
    host_entry: Host | None,
    command: str,
    timeout: int,
    input_data: str | None,
    ssh_opts: SSHConnectionOptions,
) -> Any:
    """Execute SSH command with proper options."""
    if host_entry:
        from merlya.ssh import SSHConnectionOptions

        opts = SSHConnectionOptions(
            port=host_entry.port,
            connect_timeout=ssh_opts.connect_timeout,
        )
        # Copy jump host config if present
        if ssh_opts.jump_host:
            opts.jump_host = ssh_opts.jump_host
            opts.jump_port = ssh_opts.jump_port
            opts.jump_username = ssh_opts.jump_username
            opts.jump_private_key = ssh_opts.jump_private_key

        return await ssh_pool.execute(
            host=host_entry.hostname,
            command=command,
            timeout=timeout,
            input_data=input_data,
            username=host_entry.username,
            private_key=host_entry.private_key,
            options=opts,
            host_name=host,
        )

    return await ssh_pool.execute(
        host=host,
        command=command,
        timeout=timeout,
        input_data=input_data,
        options=ssh_opts,
        host_name=host,
    )


async def _execute_with_elevation(
    ctx: SharedContext,
    ssh_pool: SSHPool,
    host: str,
    host_entry: Host | None,
    base_command: str,
    timeout: int,
    ssh_opts: SSHConnectionOptions,
    initial_result: Any,
) -> tuple[Any, str | None]:
    """Execute command with automatic elevation."""
    password_prompted = False
    elevation_used = None

    try:
        elevated_cmd, elevated_input, method = await _handle_auto_elevation(ctx, host, base_command)

        if not method:
            return initial_result, None

        elevation_used = method
        result = await _execute_ssh(
            ssh_pool, host, host_entry, elevated_cmd, timeout, elevated_input, ssh_opts
        )
        logger.debug(f"🔒 Elevation with {method}: exit_code={result.exit_code}")

        # Retry with password if auth failed and we haven't prompted yet
        auth_errors = (
            "authentication failure",
            "sorry",
            "incorrect password",
            "permission denied",
            "must be run from a terminal",
        )
        needs_password_retry = (
            result.exit_code != 0
            and not password_prompted
            and method in ("su", "sudo_with_password")
            and any(err in result.stderr.lower() for err in auth_errors)
        )

        if needs_password_retry:
            retry = await _retry_with_password(ctx, host, base_command, method, result)
            if retry:
                elevated_cmd, elevated_input = retry
                result = await _execute_ssh(
                    ssh_pool, host, host_entry, elevated_cmd, timeout, elevated_input, ssh_opts
                )
                logger.debug(f"🔒 Elevation retry with password: exit_code={result.exit_code}")

        return result, elevation_used

    except Exception as elev_exc:
        logger.warning(f"🔒 Auto-elevation failed: {type(elev_exc).__name__}: {elev_exc}")
        return initial_result, None
