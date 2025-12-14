"""
Merlya Tools - SSH execution.

Execute commands on remote hosts via SSH with automatic elevation.
"""

from __future__ import annotations

import asyncio
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
from merlya.tools.core.ssh_elevation import execute_with_elevation
from merlya.tools.core.ssh_errors import explain_ssh_error
from merlya.tools.core.ssh_models import (
    ElevationPayload,
    ExecutionContext,
    SSHResultProtocol,
)
from merlya.tools.core.ssh_patterns import (
    ELEVATION_KEYWORDS,
    needs_elevation,
    strip_sudo_prefix,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.ssh import SSHConnectionOptions


async def ssh_execute(
    ctx: SharedContext,
    host: str,
    command: str,
    timeout: int = 60,
    connect_timeout: int | None = None,
    elevation: dict[str, object] | None = None,
    via: str | None = None,
    auto_elevate: bool = True,
) -> ToolResult:
    """
    Execute a command on a host via SSH.

    Args:
        ctx: Shared context.
        host: Host name or hostname.
        command: Command to execute. Can contain @secret-name references.
        timeout: Command timeout in seconds.
        connect_timeout: Optional connection timeout.
        elevation: Optional prepared elevation payload.
        via: Optional jump host/bastion.
        auto_elevate: Auto-retry with elevation on permission errors.
    """
    safe_command = command

    try:
        # Validate and prepare command
        command, safe_command, force_elevate, error = await _prepare_command(ctx, host, command)
        if error:
            return error

        # Build execution context
        exec_ctx = await _build_context(
            ctx, host, command, timeout, connect_timeout, via, elevation
        )

        # Execute and handle auto-elevation
        # If LLM stripped sudo prefix, force elevation mode
        should_elevate = auto_elevate or force_elevate
        result, elevation_used = await _run_with_elevation(
            ctx, exec_ctx, should_elevate, force_elevate
        )

        return _build_result(result, exec_ctx, safe_command, elevation_used, force_elevate)

    except asyncio.CancelledError:
        # Propagate cancellation so REPL Ctrl+C can abort long-running actions/prompts.
        raise
    except Exception as e:
        return _handle_error(e, host, safe_command, via)


async def _prepare_command(
    ctx: SharedContext, host: str, command: str
) -> tuple[str, str, bool, ToolResult | None]:
    """Validate and prepare command for execution.

    Returns:
        Tuple of (command, safe_command, force_elevate, error).
    """
    original = command
    command, stripped = strip_sudo_prefix(command)
    force_elevate = False

    if stripped:
        logger.warning(f"⚠️ Stripped '{stripped}' - will force elevation.")
        force_elevate = True  # LLM explicitly requested elevation

    unsafe = detect_unsafe_password(command)
    if unsafe:
        logger.warning(unsafe)
        error = ToolResult(
            success=False,
            error=unsafe,
            data={"host": host, "command": original[:50] + "..."},
        )
        return "", original, False, error

    resolved, safe = await resolve_all_references(command, ctx)
    return resolved, safe, force_elevate, None


async def _build_context(
    ctx: SharedContext,
    host: str,
    command: str,
    timeout: int,
    connect_timeout: int | None,
    via: str | None,
    elevation: dict[str, object] | None,
) -> ExecutionContext:
    """Build execution context with all required components."""
    host_entry: Host | None = await ctx.hosts.get_by_name(host)
    if not host_entry:
        _log_host_resolution(host)

    ssh_opts, jump = await _build_ssh_options(ctx, host_entry, via, connect_timeout)
    ssh_pool = await ctx.get_ssh_pool()
    ensure_callbacks(ctx, ssh_pool)

    exec_ctx = ExecutionContext(
        ssh_pool=ssh_pool,
        host=host,
        host_entry=host_entry,
        ssh_opts=ssh_opts,
        timeout=timeout,
        jump_host_name=jump,
        base_command=command,
    )

    if elevation:
        _apply_elevation(ctx, elevation, command, exec_ctx)

    return exec_ctx


def _apply_elevation(
    ctx: SharedContext, elevation: dict[str, object], command: str, exec_ctx: ExecutionContext
) -> None:
    """Apply elevation data to execution context."""
    payload = ElevationPayload.from_dict(elevation)
    if not payload:
        return

    exec_ctx.base_command = payload.base_command or command
    exec_ctx.elevation_method = payload.method

    # Get password from secure cache
    if payload.input_ref and hasattr(ctx, "_elevation_cache"):
        cached = ctx._elevation_cache.get(payload.input_ref)
        if cached:
            exec_ctx.input_data = cached.get("input_data")
            del ctx._elevation_cache[payload.input_ref]
    elif payload.input:
        logger.warning("⚠️ SECURITY: Raw password in elevation (deprecated).")
        exec_ctx.input_data = payload.input


async def _run_with_elevation(
    ctx: SharedContext,
    exec_ctx: ExecutionContext,
    auto_elevate: bool,
    force_elevate: bool = False,
) -> tuple[SSHResultProtocol, str | None]:
    """Execute command with optional auto-elevation.

    Args:
        ctx: Shared context.
        exec_ctx: Execution context.
        auto_elevate: Auto-retry with elevation on permission errors.
        force_elevate: Skip initial attempt and go straight to elevation.
    """
    elevation_used = exec_ctx.elevation_method

    # If force_elevate, skip the initial non-elevated attempt
    if force_elevate and not elevation_used:
        logger.info(f"🔒 Forced elevation on {exec_ctx.host}...")
        # Create a dummy failed result to trigger elevation
        from merlya.tools.core.ssh_models import _DummyFailedResult

        dummy_result = _DummyFailedResult()
        result, elevation_used = await execute_with_elevation(
            ctx,
            exec_ctx.ssh_pool,
            exec_ctx.host,
            exec_ctx.host_entry,
            exec_ctx.base_command,
            exec_ctx.timeout,
            exec_ctx.ssh_opts,
            dummy_result,
            execute_ssh_command,
        )
        return result, elevation_used

    # Normal flow: try without elevation first
    result = await execute_ssh_command(
        exec_ctx.ssh_pool,
        exec_ctx.host,
        exec_ctx.host_entry,
        exec_ctx.base_command,
        exec_ctx.timeout,
        exec_ctx.input_data,
        exec_ctx.ssh_opts,
    )

    if _should_auto_elevate(result, elevation_used, auto_elevate, exec_ctx.base_command):
        logger.info(f"🔒 Permission denied on {exec_ctx.host}, elevating...")
        result, elevation_used = await execute_with_elevation(
            ctx,
            exec_ctx.ssh_pool,
            exec_ctx.host,
            exec_ctx.host_entry,
            exec_ctx.base_command,
            exec_ctx.timeout,
            exec_ctx.ssh_opts,
            result,
            execute_ssh_command,
        )
    elif auto_elevate and not elevation_used and result.exit_code != 0:
        # Some commands fail without a clear "permission denied" string.
        # As a fallback, only attempt elevation for commands that are likely privileged.
        try:
            permissions = await ctx.get_permissions()
            if permissions.requires_elevation(exec_ctx.base_command):
                logger.info(f"🔒 Privileged command failed on {exec_ctx.host}, elevating...")
                result, elevation_used = await execute_with_elevation(
                    ctx,
                    exec_ctx.ssh_pool,
                    exec_ctx.host,
                    exec_ctx.host_entry,
                    exec_ctx.base_command,
                    exec_ctx.timeout,
                    exec_ctx.ssh_opts,
                    result,
                    execute_ssh_command,
                )
        except Exception:
            pass

    return result, elevation_used


def _build_result(
    result: SSHResultProtocol,
    exec_ctx: ExecutionContext,
    safe_command: str,
    elevation_used: str | None,
    sudo_stripped: bool = False,
) -> ToolResult:
    """Build ToolResult from execution result."""
    cmd = safe_command[:50] + "..." if len(safe_command) > 50 else safe_command
    data = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "host": exec_ctx.host,
        "command": cmd,
        "elevation": elevation_used,
        "via": exec_ctx.jump_host_name,
    }

    # Add hint for LLM when sudo was stripped
    if sudo_stripped and elevation_used:
        data["_hint"] = (
            f"NOTE: 'sudo' is not available on {exec_ctx.host}. "
            f"Elevation was done via '{elevation_used}'. "
            "Do NOT prefix commands with 'sudo' for this host."
        )

    return ToolResult(
        success=result.exit_code == 0,
        data=data,
        error=result.stderr if result.exit_code != 0 else None,
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


def _should_auto_elevate(
    result: SSHResultProtocol,
    elevation_used: str | None,
    auto_elevate: bool,
    command: str = "",
) -> bool:
    """Check if auto-elevation should be attempted.

    Triggers on:
    - Permission denied in stderr
    - Exit code 2 on privileged paths (/root/, /etc/shadow, etc.)
    """
    if result.exit_code == 0 or elevation_used or not auto_elevate:
        return False

    # Check stderr/stdout for permission errors (some commands log permission issues to stdout)
    combined = f"{result.stderr}\n{result.stdout}".strip()
    if combined and needs_elevation(combined):
        return True

    # Exit code 2 on privileged paths likely means permission denied
    # (ls returns 2 for "cannot access", but without clear stderr sometimes)
    if result.exit_code == 2:
        privileged_paths = ("/root/", "/root ", "/etc/shadow", "/etc/sudoers")
        if any(path in command for path in privileged_paths):
            logger.debug("🔒 Exit code 2 on privileged path, assuming permission denied")
            return True

    return False
