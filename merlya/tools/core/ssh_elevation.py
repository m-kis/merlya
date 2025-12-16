"""
Merlya Tools - SSH elevation logic.

Automatic privilege elevation for remote commands.

Elevation chain (tries in order until success):
1. sudo (NOPASSWD) - if user has passwordless sudo
2. doas (NOPASSWD) - if doas is available without password
3. sudo_with_password - requires user's password
4. doas_with_password - requires user's password
5. su - requires root password (last resort)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core.ssh_models import SSHResultProtocol
from merlya.tools.core.ssh_patterns import AUTH_ERROR_PATTERNS, PASSWORD_METHODS

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.ssh import SSHConnectionOptions, SSHPool

# Type alias for SSH execute function
ExecuteFn = Callable[
    ["SSHPool", str, "Host | None", str, int, str | None, "SSHConnectionOptions"],
    Awaitable[SSHResultProtocol],
]

_ELEVATION_ORDER = ["sudo", "doas", "sudo_with_password", "doas_with_password", "su"]

# User-friendly method names for prompts
METHOD_DISPLAY: dict[str, str] = {
    "sudo_with_password": "sudo (your password)",
    "doas_with_password": "doas (your password)",
    "su": "su (root password)",
}

# Methods that use different passwords
USER_PASSWORD_METHODS = {"sudo_with_password", "doas_with_password"}
ROOT_PASSWORD_METHODS = {"su"}


async def handle_auto_elevation(
    ctx: SharedContext, host: str, base_command: str
) -> tuple[str, str | None, str | None]:
    """
    Handle automatic elevation on permission errors.

    Returns:
        Tuple of (elevated_command, input_data, method).
    """
    permissions = await ctx.get_permissions()
    result = await permissions.prepare_command(host, base_command)

    if not result.method:
        return base_command, None, None

    cmd, input_data, method = result.command, result.input_data, result.method

    if result.needs_password and not input_data:
        input_data = await _prompt_password(ctx, host, method)
        if input_data:
            permissions.cache_password(host, input_data, method)
            caps = await permissions.detect_capabilities(host)
            cmd, input_data = permissions.elevate_command(base_command, caps, method, input_data)

    return cmd, input_data, method


async def _prompt_password(ctx: SharedContext, host: str, method: str) -> str | None:
    """Prompt for password based on elevation method."""
    if method in ROOT_PASSWORD_METHODS:
        return await ctx.ui.prompt_secret(f"🔑 Root password for {host}")
    return await ctx.ui.prompt_secret("🔑 Your password for elevation")


async def retry_with_method(
    ctx: SharedContext,
    host: str,
    command: str,
    method: str,
    capabilities: dict[str, Any] | None = None,
) -> tuple[str, str | None] | None:
    """Retry elevation with a specific method."""
    if method not in PASSWORD_METHODS:
        return None

    display = METHOD_DISPLAY.get(method, method)
    logger.debug(f"🔒 Trying {method}...")
    password = await ctx.ui.prompt_secret(f"🔑 {display}")

    if not password:
        return None

    permissions = await ctx.get_permissions()
    caps = capabilities or await permissions.detect_capabilities(host)

    # Don't cache yet - will be cached after verification in _try_fallback_chain
    return permissions.elevate_command(command, caps, method, password)


async def _verify_elevation(
    ctx: SharedContext,
    ssh_pool: SSHPool,
    host: str,
    host_entry: Host | None,
    method: str,
    password: str | None,
    caps: dict[str, Any],
    timeout: int,
    ssh_opts: SSHConnectionOptions,
    execute_fn: ExecuteFn,
) -> bool:
    """Verify elevation works by running a test command.

    Returns True if elevation succeeds (whoami returns 'root').
    """
    permissions = await ctx.get_permissions()
    test_cmd, test_input = permissions.elevate_command("whoami", caps, method, password)

    try:
        result = await execute_fn(
            ssh_pool, host, host_entry, test_cmd, timeout, test_input, ssh_opts
        )
        stdout = result.stdout.strip() if result.stdout else ""
        if result.exit_code == 0 and stdout == "root":
            logger.debug(f"🔒 Elevation verified for {method} on {host}")
            return True
        logger.debug(f"🔒 Elevation test failed: exit={result.exit_code}, stdout='{stdout[:30]}'")
        return False
    except TimeoutError:
        logger.debug(f"🔒 Elevation test timed out for {method} on {host}")
        return False
    except Exception as e:
        logger.debug(f"🔒 Elevation test error for {method} on {host}: {e}")
        return False


def _is_auth_failure(stderr: str) -> bool:
    """Check if stderr indicates authentication failure."""
    lower = stderr.lower()
    return any(err in lower for err in AUTH_ERROR_PATTERNS)


async def execute_with_elevation(
    ctx: SharedContext,
    ssh_pool: SSHPool,
    host: str,
    host_entry: Host | None,
    base_command: str,
    timeout: int,
    ssh_opts: SSHConnectionOptions,
    initial_result: SSHResultProtocol,
    execute_fn: ExecuteFn,
) -> tuple[SSHResultProtocol, str | None]:
    """Execute command with automatic elevation and fallback chain.

    Security:
    - Passwords are stored in keyring, never in memory or logs
    - Failed methods are tracked to prevent retry loops
    - Timeout during elevation is treated as auth failure (wrong password)
    """
    method: str | None = None
    try:
        cmd, input_data, method = await handle_auto_elevation(ctx, host, base_command)

        if not method:
            return initial_result, None

        # Check if this method has already failed for this host
        permissions = await ctx.get_permissions()
        if permissions.is_method_failed(host, method):
            logger.warning(f"🔒 Skipping {method} for {host} (previously failed)")
            # Try fallback chain directly
            return await _try_fallback_chain(
                ctx, ssh_pool, host, host_entry, base_command,
                timeout, ssh_opts, method, initial_result, execute_fn,
            )

        result = await execute_fn(ssh_pool, host, host_entry, cmd, timeout, input_data, ssh_opts)
        logger.debug(f"🔒 Elevation with {method}: exit={result.exit_code}")

        # Try fallback chain if auth failed
        is_auth_fail = _is_auth_failure(result.stderr)
        stderr_preview = result.stderr[:100] if result.stderr else "(empty)"
        logger.debug(f"🔒 stderr='{stderr_preview}' is_auth_failure={is_auth_fail}")
        if is_auth_fail and result.exit_code != 0:
            # Mark this method as failed and clear its password
            permissions.mark_method_failed(host, method)
            result, method = await _try_fallback_chain(
                ctx,
                ssh_pool,
                host,
                host_entry,
                base_command,
                timeout,
                ssh_opts,
                method,
                result,
                execute_fn,
            )

        return result, method

    except TimeoutError:
        # Timeout during elevation likely means wrong password (su/sudo waiting for input)
        # Mark the method as failed and clear its password from keyring
        if method:
            permissions = await ctx.get_permissions()
            permissions.mark_method_failed(host, method)
            logger.warning(f"⚠️ Elevation timeout for {method} on {host} (likely wrong password)")
        return initial_result, None
    except asyncio.CancelledError:
        # Propagate Ctrl+C cancellation (prompt_toolkit -> CancelledError)
        raise
    except Exception as e:
        # Mark method as failed to prevent retry loops
        if method:
            try:
                permissions = await ctx.get_permissions()
                permissions.mark_method_failed(host, method)
            except Exception:
                pass  # Don't fail on cleanup
        logger.warning(f"🔒 Auto-elevation failed: {type(e).__name__}: {e}")
        return initial_result, None


async def _try_fallback_chain(
    ctx: SharedContext,
    ssh_pool: SSHPool,
    host: str,
    host_entry: Host | None,
    command: str,
    timeout: int,
    ssh_opts: SSHConnectionOptions,
    current_method: str,
    result: SSHResultProtocol,
    execute_fn: ExecuteFn,
) -> tuple[SSHResultProtocol, str]:
    """Try fallback chain until success or exhausted.

    Flow:
    1. Get available methods (excluding already failed ones)
    2. For each method: prompt for password, VERIFY with test, then run actual command
    3. Cache password only after verification succeeds
    4. Mark as failed and try next if verification fails

    Security:
    - Skips methods that have previously failed (prevents retry loops)
    - Verifies elevation works before caching password
    - Clears passwords from keyring on failure
    """
    permissions = await ctx.get_permissions()
    caps = await permissions.detect_capabilities(host)

    available_raw = caps.get("available_methods", [])
    available: list[str] = []
    if isinstance(available_raw, list):
        for item in available_raw:
            if isinstance(item, dict):
                method = item.get("method")
                if isinstance(method, str):
                    available.append(method)

    # Preserve the documented elevation order and only try methods that exist on the host.
    available_set = set(available)
    if current_method in _ELEVATION_ORDER:
        start_idx = _ELEVATION_ORDER.index(current_method) + 1
    else:
        start_idx = 0

    # Filter out methods that have already failed (prevents infinite loops)
    candidates = [
        m for m in _ELEVATION_ORDER[start_idx:]
        if m in available_set and not permissions.is_method_failed(host, m)
    ]

    if not candidates:
        logger.warning(f"🔒 No more elevation methods available for {host}")
        ctx.ui.warning(f"No elevation methods left for {host}. Use `/ssh elevation reset {host}` to retry.")
        return result, current_method

    # Show available fallbacks once
    ctx.ui.info(f"🔒 Trying fallback methods: {', '.join(candidates)}")

    last_result = result
    last_method = current_method

    for next_method in candidates:
        display = METHOD_DISPLAY.get(next_method, next_method)
        password: str | None = None

        # Prompt for password if needed
        if next_method in PASSWORD_METHODS:
            password = await ctx.ui.prompt_secret(f"🔑 {display}")
            if not password:
                logger.debug(f"🔒 Skipped {next_method} (no password)")
                continue

        # VERIFY elevation works before proceeding
        ctx.ui.info(f"🔐 Verifying {next_method}...")
        verified = await _verify_elevation(
            ctx, ssh_pool, host, host_entry, next_method, password,
            caps, timeout, ssh_opts, execute_fn
        )

        if not verified:
            ctx.ui.warning(f"❌ {next_method} failed (wrong password?)")
            permissions.mark_method_failed(host, next_method)
            continue

        # Verification succeeded - cache password and run actual command
        if password:
            permissions.cache_password(host, password, next_method)
        ctx.ui.success(f"✅ {next_method} verified")

        # Now run the actual command
        cmd, input_data = permissions.elevate_command(command, caps, next_method, password)
        try:
            new_result = await execute_fn(
                ssh_pool, host, host_entry, cmd, timeout, input_data, ssh_opts
            )
        except TimeoutError:
            logger.warning(f"⚠️ Command timeout with {next_method} on {host}")
            last_method = next_method
            continue

        logger.debug(f"🔒 Command with {next_method}: exit={new_result.exit_code}")
        return new_result, next_method

    return last_result, last_method
