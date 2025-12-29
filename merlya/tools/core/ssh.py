"""
Merlya Tools - SSH execution.

Execute commands on remote hosts via SSH.

NOTE: Auto-elevation has been removed for simplicity. If a command needs
elevated privileges, the LLM should prefix it with 'sudo' (or 'doas', 'su -c').
If a password is needed, use the request_credentials tool first.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.resolve import resolve_all_references
from merlya.tools.core.security import detect_unsafe_password
from merlya.tools.core.ssh_connection import (
    ensure_callbacks,
    execute_ssh_command,
    is_ip_address,
    resolve_jump_host,
)
from merlya.tools.core.ssh_errors import explain_ssh_error
from merlya.tools.core.ssh_models import ExecutionContext, SSHResultProtocol
from merlya.tools.core.ssh_patterns import ELEVATION_KEYWORDS

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.ssh import SSHConnectionOptions

# Valid keywords for the field part of @service:host:field references
_VALID_SECRET_KEYWORDS = frozenset({"password", "passwd", "pass", "key", "token", "secret"})


def _needs_elevation_password(command: str) -> bool:
    """
    Check if a command requires elevation password.

    Detects commands that need password-based elevation:
    - sudo -s (shell mode) and sudo -S (stdin mode) - case insensitive
    - su commands - case insensitive

    Args:
        command: The command string to check.

    Returns:
        True if the command requires elevation password, False otherwise.
    """
    cmd_lower = command.lower()
    # Check if command starts with sudo and contains -S or -s flag
    has_sudo_stdin = cmd_lower.startswith("sudo ") and (
        " -s " in cmd_lower or " -s" in cmd_lower or cmd_lower.startswith("sudo -s")
    )
    return has_sudo_stdin or cmd_lower.startswith("su ")


def _redact_potential_password(stdin: str) -> str:
    """
    Redact potential passwords in stdin references.

    If the agent mistakenly puts the actual password in the reference
    (e.g., @root:host:actualpassword instead of @root:host:password),
    we redact it for logging.

    Args:
        stdin: The stdin reference string (e.g., "@root:host:password").

    Returns:
        Safe string with potential password redacted.
    """
    if not stdin.startswith("@"):
        return "[REDACTED]"

    ref = stdin[1:]  # Remove @
    parts = ref.split(":")

    if len(parts) >= 3:
        service, host, field = parts[0], parts[1], parts[2]
        # If field is not a known keyword, it might be the actual password
        if field.lower() not in _VALID_SECRET_KEYWORDS:
            return f"@{service}:{host}:[REDACTED]"

    return stdin


async def ssh_execute(
    ctx: SharedContext,
    host: str,
    command: str,
    timeout: int = 60,
    connect_timeout: int | None = None,
    via: str | None = None,
    stdin: str | None = None,
) -> ToolResult:
    """
    Execute a command on a host via SSH.

    Args:
        ctx: Shared context.
        host: Host name or hostname. Accepts @hostname format (@ will be stripped).
        command: Command to execute. Can contain @secret-name references.
        timeout: Command timeout in seconds.
        connect_timeout: Optional connection timeout.
        via: Optional jump host/bastion.
        stdin: Password for su/sudo -S as @service:host:password reference.
               Format: @sudo:192.168.1.7:password or @root:hostname:password

    Privilege Elevation:
    - `sudo <command>` : passwordless sudo
    - `sudo -S <command>` with stdin="@sudo:host:password" : sudo with password via stdin
    - `su -c '<command>'` with stdin="@root:host:password" : su with password (uses PTY)
    - `doas <command>` : doas (usually passwordless)

    Secret Format: @service:host:field (e.g., @sudo:192.168.1.7:password)
    Use request_credentials(service='sudo', host='hostname') to store credentials first.
    """
    safe_command = command

    # VALIDATION: Detect common LLM mistake of passing password reference as host
    if host.startswith("@") and any(
        kw in host.lower() for kw in ["secret", "password", "sudo", "root", "cred"]
    ):
        return ToolResult(
            success=False,
            error=(
                f"❌ WRONG PARAMETER: '{host}' looks like a password reference, not a host!\n"
                "The 'host' parameter must be a machine IP/hostname (e.g., '192.168.1.7').\n"
                "Use 'stdin' parameter for passwords: ssh_execute(host='192.168.1.7', command='sudo -S ...', stdin='@secret-sudo')"
            ),
            data={"host": host},
        )

    # Strip @ prefix from host if present (LLM may pass @hostname format)
    if host.startswith("@"):
        host = host[1:]
        logger.debug(f"🖥️ Stripped @ prefix, using host: {host}")

    # Handle "local" target - execute locally without SSH
    if host.lower() in ("local", "localhost", "127.0.0.1", "::1"):
        logger.info(f"🖥️ Running locally: {command[:50]}...")
        from merlya.tools.core.bash import bash_execute

        return await bash_execute(ctx, command, timeout=timeout)

    try:
        # Validate and prepare command
        command, safe_command, error = await _prepare_command(ctx, host, command)
        if error:
            return error

        # Resolve stdin if it's a @secret reference
        input_data: str | None = None
        if stdin:
            logger.debug(f"🔑 stdin parameter provided: {stdin[:20]}...")
            if not stdin.startswith("@"):
                # SECURITY: stdin must be a @secret reference, not plaintext password
                return ToolResult(
                    success=False,
                    error=(
                        "🔐 stdin must be a @secret-xxx reference, not plaintext. "
                        "Use request_credentials() first to store the password securely."
                    ),
                    data={"host": host},
                )
            # Resolve the @secret reference to get the actual password
            resolved_stdin, _ = await resolve_all_references(stdin, ctx)
            if resolved_stdin == stdin:
                # Secret not found in keyring - redact potential passwords
                # Format: @service:host:field - if field is not a keyword, it might be a password
                safe_stdin = _redact_potential_password(stdin)
                logger.warning(f"🔐 Secret '{safe_stdin}' not found in keyring")
                return ToolResult(
                    success=False,
                    error=f"🔐 Secret '{safe_stdin}' not found. Use request_credentials() to store it first.",
                    data={"host": host},
                )
            input_data = resolved_stdin
            logger.debug(f"🔑 stdin resolved successfully (length: {len(input_data)} chars)")
        else:
            # Check if command needs stdin but it wasn't provided
            # Try to auto-resolve from secrets store for known elevation patterns
            input_data = await _auto_resolve_elevation_password(ctx, host, command)
            if input_data is None and _needs_elevation_password(command):
                # Check if we're in non-interactive mode
                is_non_interactive = ctx.auto_confirm or getattr(ctx.ui, "auto_confirm", False)
                short_cmd = command[:40] + "..." if len(command) > 40 else command

                if is_non_interactive:
                    # In non-interactive mode, credentials can NEVER be obtained
                    # Return a clear error that tells the agent to STOP trying
                    return ToolResult(
                        success=False,
                        error=(
                            f"🔐 ELEVATION IMPOSSIBLE in non-interactive mode.\n\n"
                            f"Command '{short_cmd}' requires sudo/su password, but:\n"
                            f"- No password found in keyring for {host}\n"
                            f"- Cannot prompt user (--yes mode)\n\n"
                            f"SOLUTIONS (before running with --yes):\n"
                            f"1. Store password: merlya secret set sudo:{host}:password\n"
                            f"2. Configure NOPASSWD sudo on {host}\n"
                            f"3. Run in interactive mode (without --yes)\n\n"
                            f"⚠️ DO NOT retry elevated commands - they will always fail."
                        ),
                        data={
                            "host": host,
                            "command": command[:50],
                            "needs_credentials": True,
                            "non_interactive": True,
                            "permanent_failure": True,
                        },
                    )
                else:
                    # Interactive mode - tell agent to request credentials
                    return ToolResult(
                        success=False,
                        error=(
                            f"🔐 ELEVATION REQUIRED: Command '{short_cmd}' needs a password.\n\n"
                            f"The password for {host} was not found in the secrets store.\n\n"
                            f"To fix this:\n"
                            f"1. Call: request_credentials(service='sudo', host='{host}')\n"
                            f"2. Then retry with: ssh_execute(host='{host}', command='{short_cmd}', stdin='@sudo:{host}:password')\n\n"
                            f"⚠️ DO NOT execute without stdin - it will timeout waiting for password input."
                        ),
                        data={"host": host, "command": command[:50], "needs_credentials": True},
                    )

        # Lookup host entry early to get elevation_method
        host_entry: Host | None = await ctx.hosts.get_by_name(host)

        # Auto-transform command based on known elevation method
        # Priority: Host model > memory cache
        host_elevation = getattr(host_entry, "elevation_method", None) if host_entry else None
        command = _auto_transform_elevation_command(host, command, host_elevation)

        # Build execution context (reuses host_entry lookup)
        exec_ctx = await _build_context(
            ctx, host, command, timeout, connect_timeout, via, host_entry
        )

        # Execute command (input_data enables PTY for su/sudo -S automatically)
        result = await execute_ssh_command(
            exec_ctx.ssh_pool,
            exec_ctx.host,
            exec_ctx.host_entry,
            exec_ctx.base_command,
            exec_ctx.timeout,
            input_data,
            exec_ctx.ssh_opts,
        )

        return _build_result(result, exec_ctx, safe_command)

    except asyncio.CancelledError:
        # Propagate cancellation so REPL Ctrl+C can abort long-running actions/prompts.
        raise
    except Exception as e:
        return _handle_error(e, host, safe_command, via)


# Global credential hints: maps host -> secret_key for custom password references
# Example: {"192.168.1.7": "pine-pass"} means @pine-pass is the password for that host
# Thread-safe with lock for concurrent agent execution
_credential_hints: dict[str, str] = {}
_credential_hints_lock = threading.Lock()


def set_credential_hint(host: str, secret_key: str) -> None:
    """
    Set a credential hint for a host.

    When user mentions @secret-name for a specific host, call this to remember
    the association. The auto-resolution will use this hint.

    Args:
        host: Target host (e.g., "192.168.1.7").
        secret_key: Secret key without @ prefix (e.g., "pine-pass").
    """
    # Normalize host to lowercase
    host_lower = host.lower()
    # Strip @ prefix if present
    key = secret_key.lstrip("@")
    with _credential_hints_lock:
        _credential_hints[host_lower] = key
    logger.info(f"🔑 Credential hint set: {host} -> @{key}")


def get_credential_hint(host: str) -> str | None:
    """Get credential hint for a host."""
    with _credential_hints_lock:
        return _credential_hints.get(host.lower())


def clear_credential_hints() -> None:
    """Clear all credential hints."""
    with _credential_hints_lock:
        _credential_hints.clear()


async def _auto_resolve_elevation_password(
    ctx: SharedContext, host: str, command: str
) -> str | None:
    """
    Auto-resolve elevation password from secrets store.

    Checks if the command needs elevation (su/sudo -S) and tries to find
    a cached password in the secrets store.

    Priority order:
    1. Credential hint (user-provided @secret-name for this host)
    2. Standard keys (root:{host}:password, sudo:{host}:password)

    Args:
        ctx: Shared context.
        host: Target host.
        command: Command to execute.

    Returns:
        Password if found, None otherwise.
    """
    from merlya.tools.core.ssh_patterns import get_cached_elevation_method

    # Check if command needs password-based elevation
    if not _needs_elevation_password(command):
        return None

    # PRIORITY 1: Check credential hints (user-provided @secret references)
    hint = get_credential_hint(host)
    if hint:
        try:
            password = ctx.secrets.get(hint)
            if password:
                logger.info(f"🔑 Auto-resolved password for {host} from hint @{hint}")
                return password
        except Exception as e:
            logger.debug(f"Could not resolve hint {hint}: {e}")

    # PRIORITY 2: Check cached method to determine key order
    cached_method = get_cached_elevation_method(host)

    # Try to find password in secrets store
    # Order based on cached method (if su works, look for root: first)
    if cached_method == "su":
        secret_keys = [
            f"root:{host}:password",
            f"sudo:{host}:password",
        ]
    else:
        secret_keys = [
            f"sudo:{host}:password",
            f"root:{host}:password",
        ]

    for key in secret_keys:
        try:
            password = ctx.secrets.get(key)
            if password:
                logger.info(f"🔑 Auto-resolved elevation password for {host} from secrets store")
                return password
        except Exception as e:
            logger.debug(f"Could not check secret {key}: {e}")

    logger.debug(f"No cached elevation password found for {host}")
    return None


def _auto_transform_elevation_command(
    host: str, command: str, host_elevation_method: str | None = None
) -> str:
    """
    Auto-transform elevation commands based on known method for host.

    If the LLM uses sudo but su is what works for this host, transforms:
        sudo -S cmd  →  su -c 'cmd'

    This prevents timeouts when sudo isn't available but su is.

    Args:
        host: Target host.
        command: Command to potentially transform.
        host_elevation_method: Elevation method from Host model (preferred).

    Returns:
        Transformed command (or original if no transformation needed).
    """
    from merlya.tools.core.ssh_patterns import (
        format_elevated_command,
        get_cached_elevation_method,
        strip_sudo_prefix,
    )

    # Priority: Host model > memory cache
    known_method = host_elevation_method or get_cached_elevation_method(host)
    if not known_method:
        return command  # No known method, use command as-is

    # Check if command uses elevation
    base_cmd, prefix = strip_sudo_prefix(command)
    if not prefix:
        return command  # No elevation prefix, use as-is

    # Determine what the command is trying to use
    cmd_lower = command.lower()
    uses_sudo = cmd_lower.startswith("sudo ")
    uses_su = cmd_lower.startswith("su ")

    # Transform if mismatch between command and known method
    if uses_sudo and known_method == "su":
        # LLM used sudo but su is what works
        transformed = format_elevated_command(base_cmd, "su")
        logger.info(f"🔄 Auto-transformed: sudo → su -c for {host}")
        logger.debug(f"   Original: {command[:50]}")
        logger.debug(f"   Transformed: {transformed[:50]}")
        return transformed

    if uses_su and known_method in ("sudo", "sudo-S"):
        # LLM used su but sudo is what works
        method = "sudo-S" if "-s" in command.lower() else "sudo"
        transformed = format_elevated_command(base_cmd, method)
        logger.info(f"🔄 Auto-transformed: su → sudo for {host}")
        return transformed

    return command  # No transformation needed


async def _prepare_command(
    ctx: SharedContext, host: str, command: str
) -> tuple[str, str, ToolResult | None]:
    """Validate and prepare command for execution.

    Returns:
        Tuple of (command, safe_command, error).
    """
    unsafe = detect_unsafe_password(command)
    if unsafe:
        logger.warning(unsafe)
        error = ToolResult(
            success=False,
            error=unsafe,
            data={"host": host, "command": "[MASKED]"},
        )
        return "", command, error

    resolved, safe = await resolve_all_references(command, ctx)
    return resolved, safe, None


async def _build_context(
    ctx: SharedContext,
    host: str,
    command: str,
    timeout: int,
    connect_timeout: int | None,
    via: str | None,
    host_entry: Host | None = None,
) -> ExecutionContext:
    """Build execution context with all required components."""
    # Use provided host_entry or lookup if not provided
    if host_entry is None:
        host_entry = await ctx.hosts.get_by_name(host)
    if not host_entry:
        _log_host_resolution(host)

    ssh_opts, jump = await _build_ssh_options(ctx, host_entry, via, connect_timeout)
    ssh_pool = await ctx.get_ssh_pool()
    ensure_callbacks(ctx, ssh_pool)

    return ExecutionContext(
        ssh_pool=ssh_pool,
        host=host,
        host_entry=host_entry,
        ssh_opts=ssh_opts,
        timeout=timeout,
        jump_host_name=jump,
        base_command=command,
    )


def _build_result(
    result: SSHResultProtocol,
    exec_ctx: ExecutionContext,
    safe_command: str,
) -> ToolResult:
    """Build ToolResult from execution result."""
    from merlya.tools.core.ssh_patterns import is_auth_error, needs_elevation

    cmd = safe_command[:50] + "..." if len(safe_command) > 50 else safe_command
    data = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "host": exec_ctx.host,
        "command": cmd,
        "via": exec_ctx.jump_host_name,
    }

    error_msg = result.stderr if result.exit_code != 0 else None

    # Add hints when elevation is needed or auth failed
    if result.exit_code != 0:
        cmd_lower = safe_command.lower()
        is_sudo_cmd = cmd_lower.startswith("sudo ") or "sudo " in cmd_lower

        if needs_elevation(result.stderr):
            data["hint"] = (
                f"PERMISSION DENIED on {exec_ctx.host}. To elevate privileges:\n"
                f"1. Call: request_credentials(service='sudo', host='{exec_ctx.host}')\n"
                f"2. Then: ssh_execute(host='{exec_ctx.host}', command='sudo -S <cmd>', stdin='@sudo:{exec_ctx.host}:password')\n"
                f"⚠️ DO NOT use bash() - it runs LOCALLY, not on {exec_ctx.host}!"
            )
        elif is_auth_error(result.stderr):
            data["hint"] = (
                f"AUTHENTICATION FAILED on {exec_ctx.host}. The password may be wrong.\n"
                f"Call request_credentials(service='sudo', host='{exec_ctx.host}') to re-enter the password."
            )
        elif is_sudo_cmd and not result.stderr.strip():
            # Fallback: sudo failed but stderr is empty (common in non-interactive SSH)
            # The password prompt goes to TTY, not stderr, so we don't see the error
            data["hint"] = (
                f"sudo FAILED on {exec_ctx.host} (likely needs password - prompt went to TTY).\n"
                f"1. Call: request_credentials(service='sudo', host='{exec_ctx.host}')\n"
                f"2. Then: ssh_execute(host='{exec_ctx.host}', command='sudo -S <cmd>', stdin='@sudo:{exec_ctx.host}:password')\n"
                f"⚠️ DO NOT retry without stdin - it will fail the same way!"
            )

    return ToolResult(
        success=result.exit_code == 0,
        data=data,
        error=error_msg,
    )


def _handle_error(e: Exception, host: str, command: str, via: str | None) -> ToolResult:
    """Handle SSH execution error."""
    info = explain_ssh_error(e, host, via=via)
    logger.error(f"SSH failed: {info.symptom}")
    logger.info(f"💡 {info.suggestion}")
    return ToolResult(
        success=False,
        data={
            "host": host,
            "command": command[:50],
            "symptom": info.symptom,
            "explanation": info.explanation,
            "suggestion": info.suggestion,
        },
        error=f"{info.symptom} - {info.explanation}",
    )


def _log_host_resolution(host: str) -> None:
    """Log host resolution status."""
    if is_ip_address(host):
        logger.debug(f"Using direct IP: {host}")
    else:
        logger.debug(f"Host '{host}' not in inventory, trying direct")


async def _build_ssh_options(
    ctx: SharedContext,
    host_entry: Host | None,
    via: str | None,
    connect_timeout: int | None,
) -> tuple[SSHConnectionOptions, str | None]:
    """Build SSH connection options with jump host resolution."""
    from merlya.ssh import SSHConnectionOptions

    opts = SSHConnectionOptions(connect_timeout=connect_timeout)

    if via and via.lower() in ELEVATION_KEYWORDS:
        logger.warning(f"⚠️ '{via}' is elevation method, not jump host.")
        via = None

    jump = via or (host_entry.jump_host if host_entry else None)

    if jump:
        cfg = await resolve_jump_host(ctx, jump)
        opts.jump_host = cfg.host
        opts.jump_port = cfg.port
        opts.jump_username = cfg.username
        opts.jump_private_key = cfg.private_key

    return opts, jump
