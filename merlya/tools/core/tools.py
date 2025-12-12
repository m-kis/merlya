"""
Merlya Tools - Core tools (always active).

Includes: list_hosts, get_host, ssh_execute, ask_user, request_confirmation.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Pattern to match @secret-name references in commands
# Only match @ preceded by whitespace, start of string, or shell operators (not emails/URLs)
# Examples matched: @api-key, --password @db-pass, echo @token, @sudo:hostname:password
# Examples NOT matched: user@github.com, git@repo.com
# Now supports colons for structured keys like @service:host:field
SECRET_PATTERN = re.compile(r"(?:^|(?<=[\s;|&='\"]))\@([a-zA-Z][a-zA-Z0-9_:.-]*)")


def resolve_secrets(command: str, secrets: Any) -> tuple[str, str]:
    """
    Resolve @secret-name references in a command.

    Args:
        command: Command string potentially containing @secret-name references.
        secrets: SecretStore instance.

    Returns:
        Tuple of (resolved_command, safe_command_for_logging).
        The safe_command replaces secret values with '***'.
    """
    resolved = command
    safe = command

    # Collect all matches and sort by start position in reverse order
    # This ensures we replace from end to start, preserving span positions
    # and avoiding corruption of overlapping names (e.g., @api vs @api_key)
    matches = list(SECRET_PATTERN.finditer(command))
    matches.sort(key=lambda m: m.start(), reverse=True)

    for match in matches:
        secret_name = match.group(1)
        secret_value = secrets.get(secret_name)
        start, end = match.span(0)
        if secret_value is not None:  # Allow empty strings as valid secrets
            # Replace exact span in resolved command with actual value
            resolved = resolved[:start] + secret_value + resolved[end:]
            # Replace exact span in safe command with mask
            safe = safe[:start] + "***" + safe[end:]
            logger.debug(f"🔐 Resolved secret @{secret_name}")
        else:
            # Log warning if secret reference found but not in store
            logger.warning(f"⚠️ Secret @{secret_name} not found in store")

    return resolved, safe


# Patterns that likely contain plaintext passwords (security risk)
# These patterns detect when a password is embedded directly instead of using @secret-name references
UNSAFE_PASSWORD_PATTERNS = [
    # echo 'pass' | sudo -S (but not echo '@secret' | sudo -S)
    re.compile(r"echo\s+['\"]?(?!@)[^'\"]+['\"]?\s*\|\s*sudo\s+-S", re.IGNORECASE),
    # -p'password' or -ppassword (but not -p@secret or -p'@secret')
    re.compile(r"-p['\"]?(?!@)[^@\s'\"]+['\"]?(?:\s|$)", re.IGNORECASE),
    # --password=pass (but not --password=@secret)
    re.compile(r"--password[=\s]+['\"]?(?!@)[^@\s'\"]+['\"]?", re.IGNORECASE),
]


def detect_unsafe_password(command: str) -> str | None:
    """
    Detect if a command contains a potential plaintext password.

    Returns a warning message if unsafe pattern detected, None otherwise.
    Commands using @secret-name references are safe.
    """
    for pattern in UNSAFE_PASSWORD_PATTERNS:
        if pattern.search(command):
            return (
                "⚠️ SECURITY: Command may contain a plaintext password. "
                "Use @secret-name references instead (e.g., @sudo:host:password)."
            )
    return None


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    data: Any
    error: str | None = None


async def list_hosts(
    ctx: SharedContext,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> ToolResult:
    """
    List hosts from inventory.

    Args:
        ctx: Shared context.
        tag: Filter by tag.
        status: Filter by health status.
        limit: Maximum hosts to return.

    Returns:
        ToolResult with list of hosts.
    """
    try:
        if tag:
            hosts = await ctx.hosts.get_by_tag(tag)
        else:
            hosts = await ctx.hosts.get_all()

        # Filter by status if specified
        if status:
            hosts = [h for h in hosts if h.health_status == status]

        # Apply limit
        hosts = hosts[:limit]

        # Convert to simple dicts
        host_list = [
            {
                "name": h.name,
                "hostname": h.hostname,
                "status": h.health_status,
                "tags": h.tags,
                "last_seen": str(h.last_seen) if h.last_seen else None,
            }
            for h in hosts
        ]

        logger.debug(f"Listed {len(host_list)} hosts")
        return ToolResult(success=True, data=host_list)

    except Exception as e:
        logger.error(f"Failed to list hosts: {e}")
        return ToolResult(success=False, data=[], error=str(e))


async def get_host(
    ctx: SharedContext,
    name: str,
    include_metadata: bool = True,
) -> ToolResult:
    """
    Get detailed information about a host.

    Args:
        ctx: Shared context.
        name: Host name.
        include_metadata: Include enriched metadata.

    Returns:
        ToolResult with host details.
    """
    try:
        host = await ctx.hosts.get_by_name(name)
        if not host:
            return ToolResult(
                success=False,
                data=None,
                error=f"Host '{name}' not found",
            )

        host_data: dict[str, Any] = {
            "id": host.id,
            "name": host.name,
            "hostname": host.hostname,
            "port": host.port,
            "username": host.username,
            "tags": host.tags,
            "health_status": host.health_status,
            "last_seen": str(host.last_seen) if host.last_seen else None,
        }

        if include_metadata:
            host_data["metadata"] = host.metadata
            if host.os_info:
                host_data["os_info"] = {
                    "name": host.os_info.name,
                    "version": host.os_info.version,
                    "kernel": host.os_info.kernel,
                    "arch": host.os_info.arch,
                }

        return ToolResult(success=True, data=host_data)

    except Exception as e:
        logger.error(f"Failed to get host: {e}")
        return ToolResult(success=False, data=None, error=str(e))


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
             Can be a host name from inventory or IP/hostname.
             Takes priority over any jump_host configured in the host entry.
        auto_elevate: If True, automatically retry with elevation on permission errors.

    Returns:
        ToolResult with command output.
    """
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

        # Initialize safe_command early so it's always available in the except block
        safe_command = command

        # Resolve secrets in command (@secret-name -> actual value)
        resolved_command, safe_command = resolve_secrets(command, ctx.secrets)

        # Resolve host from inventory
        host_entry = await ctx.hosts.get_by_name(host)

        if not host_entry:
            # Allow direct IP usage without inventory
            if _is_ip(host):
                logger.debug(f"Using direct IP (no inventory) for SSH: {host}")
            else:
                return ToolResult(
                    success=False,
                    error=f"Host '{host}' not found in inventory. Use /hosts add {host} first.",
                    data={"host": host, "command": safe_command[:50]},
                )

        # Apply prepared elevation (brain-driven only)
        input_data = None
        elevation_used = None
        base_command = resolved_command

        # Build SSH connection options from host inventory
        from merlya.ssh import SSHConnectionOptions

        ssh_opts = SSHConnectionOptions(connect_timeout=connect_timeout)

        # Resolve jump host - 'via' parameter takes priority over inventory config
        jump_host_name = via or (host_entry.jump_host if host_entry else None)

        if jump_host_name:
            try:
                jump_entry = await ctx.hosts.get_by_name(jump_host_name)
            except Exception:
                jump_entry = None

            if jump_entry:
                ssh_opts.jump_host = jump_entry.hostname
                ssh_opts.jump_port = jump_entry.port
                ssh_opts.jump_username = jump_entry.username
                ssh_opts.jump_private_key = jump_entry.private_key
                logger.debug(f"🔗 Using jump host '{jump_host_name}' ({jump_entry.hostname})")
            else:
                # Use jump_host_name directly as hostname if not in inventory
                ssh_opts.jump_host = jump_host_name
                logger.debug(f"🔗 Using jump host '{jump_host_name}' (direct)")

        if elevation:
            resolved_command = elevation.get("command", resolved_command)
            base_command = elevation.get("base_command", resolved_command)
            input_data = elevation.get("input")
            elevation_used = elevation.get("method")

        # Get SSH pool
        ssh_pool = await ctx.get_ssh_pool()
        _ensure_callbacks(ctx, ssh_pool)

        async def _run(cmd: str, inp: str | None) -> Any:
            if host_entry:
                opts = SSHConnectionOptions(
                    port=host_entry.port,
                    connect_timeout=connect_timeout,
                )
                # Copy jump host config if present
                if ssh_opts.jump_host:
                    opts.jump_host = ssh_opts.jump_host
                    opts.jump_port = ssh_opts.jump_port
                    opts.jump_username = ssh_opts.jump_username
                    opts.jump_private_key = ssh_opts.jump_private_key

                return await ssh_pool.execute(
                    host=host_entry.hostname,
                    command=cmd,
                    timeout=timeout,
                    input_data=inp,
                    username=host_entry.username,
                    private_key=host_entry.private_key,
                    options=opts,
                    host_name=host,  # Pass inventory name for credential lookup
                )
            return await ssh_pool.execute(
                host=host,
                command=cmd,
                timeout=timeout,
                input_data=inp,
                options=ssh_opts,
                host_name=host,  # Pass inventory name for credential lookup
            )

        result = await _run(resolved_command, input_data)

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
            password_prompted = False
            try:
                permissions = await ctx.get_permissions()
                elevation_result = await permissions.prepare_command(host, base_command)  # type: ignore[attr-defined]

                if elevation_result.method:
                    elevated_cmd = elevation_result.command
                    elevated_input = elevation_result.input_data
                    elevation_used = elevation_result.method

                    # Get cached capabilities for elevate_command calls
                    capabilities = await permissions.detect_capabilities(host)  # type: ignore[attr-defined]

                    # If elevation needs password and we don't have input, prompt
                    if elevation_result.needs_password and not elevated_input:
                        password = await ctx.ui.prompt_secret("🔑 Elevation password required")
                        password_prompted = True
                        if password:
                            # Cache password for reuse in this session
                            permissions.cache_password(host, password)  # type: ignore[attr-defined]
                            elevated_cmd, elevated_input = permissions.elevate_command(  # type: ignore[attr-defined]
                                base_command, capabilities, elevation_used, password
                            )

                    result = await _run(elevated_cmd, elevated_input)
                    logger.debug(
                        f"🔒 Elevation with {elevation_used}: exit_code={result.exit_code}"
                    )

                    # If elevation failed due to needing password, retry with password
                    # but only if we haven't already prompted for one
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
                        and elevation_used in ("su", "sudo_with_password")
                        and any(err in result.stderr.lower() for err in auth_errors)
                    )

                    if needs_password_retry:
                        logger.debug(f"🔒 {elevation_used} requires password, prompting user...")
                        password = await ctx.ui.prompt_secret(
                            f"🔑 {elevation_used} password required"
                        )
                        if password:
                            permissions.cache_password(host, password)  # type: ignore[attr-defined]
                            elevated_cmd, elevated_input = permissions.elevate_command(  # type: ignore[attr-defined]
                                base_command, capabilities, elevation_used, password
                            )
                            result = await _run(elevated_cmd, elevated_input)
                            logger.debug(
                                f"🔒 Elevation retry with password: exit_code={result.exit_code}"
                            )
            except Exception as elev_exc:
                logger.warning(f"🔒 Auto-elevation failed: {type(elev_exc).__name__}: {elev_exc}")

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
        # Parse error for human-readable explanation
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


def _is_ip(value: str) -> bool:
    """Return True if value is a valid IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _explain_ssh_error(error: Exception, host: str, via: str | None = None) -> dict[str, str]:
    """Parse SSH error and return human-readable explanation with suggested solutions.

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


def _ensure_callbacks(ctx: SharedContext, ssh_pool: Any) -> None:
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


async def ask_user(
    ctx: SharedContext,
    question: str,
    choices: list[str] | None = None,
    default: str | None = None,
    secret: bool = False,
) -> ToolResult:
    """
    Ask the user for input.

    Args:
        ctx: Shared context.
        question: Question to ask.
        choices: Optional list of choices.
        default: Default value.
        secret: Whether to hide input.

    Returns:
        ToolResult with user response.
    """
    try:
        ui = ctx.ui

        if secret:
            response = await ui.prompt_secret(question)
        elif choices:
            response = await ui.prompt_choice(question, choices, default)
        else:
            response = await ui.prompt(question, default or "")

        return ToolResult(success=True, data=response)

    except Exception as e:
        logger.error(f"Failed to get user input: {e}")
        return ToolResult(success=False, data=None, error=str(e))


async def request_confirmation(
    ctx: SharedContext,
    action: str,
    details: str | None = None,
    risk_level: str = "moderate",
) -> ToolResult:
    """
    Request user confirmation before an action.

    Args:
        ctx: Shared context.
        action: Description of the action.
        details: Additional details.
        risk_level: Risk level (low, moderate, high, critical).

    Returns:
        ToolResult with confirmation (True/False).
    """
    try:
        ui = ctx.ui

        # Format message based on risk
        risk_icons = {
            "low": "",
            "moderate": "",
            "high": "",
            "critical": "",
        }
        icon = risk_icons.get(risk_level, "")

        message = f"{icon} {action}"
        if details:
            ui.info(f"   {details}")

        confirmed = await ui.prompt_confirm(message, default=False)

        return ToolResult(success=True, data=confirmed)

    except Exception as e:
        logger.error(f"Failed to get confirmation: {e}")
        return ToolResult(success=False, data=False, error=str(e))


# Placeholder exports for interaction tools (implemented in merlya/tools/interaction.py)
async def request_credentials(*args: Any, **kwargs: Any) -> ToolResult:  # pragma: no cover - shim
    from merlya.tools.interaction import request_credentials as _rc

    return await _rc(*args, **kwargs)  # type: ignore[return-value]


async def request_elevation(*args: Any, **kwargs: Any) -> ToolResult:  # pragma: no cover - shim
    from merlya.tools.interaction import request_elevation as _re

    return await _re(*args, **kwargs)  # type: ignore[return-value]


async def get_variable(
    ctx: SharedContext,
    name: str,
) -> ToolResult:
    """
    Get a variable value.

    Args:
        ctx: Shared context.
        name: Variable name.

    Returns:
        ToolResult with variable value.
    """
    try:
        variable = await ctx.variables.get(name)
        if variable:
            return ToolResult(success=True, data=variable.value)
        return ToolResult(
            success=False,
            data=None,
            error=f"Variable '{name}' not found",
        )
    except Exception as e:
        logger.error(f"Failed to get variable: {e}")
        return ToolResult(success=False, data=None, error=str(e))


async def set_variable(
    ctx: SharedContext,
    name: str,
    value: str,
    is_env: bool = False,
) -> ToolResult:
    """
    Set a variable.

    Args:
        ctx: Shared context.
        name: Variable name.
        value: Variable value.
        is_env: Whether to export as environment variable.

    Returns:
        ToolResult confirming set.
    """
    try:
        await ctx.variables.set(name, value, is_env=is_env)
        return ToolResult(success=True, data={"name": name, "is_env": is_env})
    except Exception as e:
        logger.error(f"Failed to set variable: {e}")
        return ToolResult(success=False, data=None, error=str(e))
