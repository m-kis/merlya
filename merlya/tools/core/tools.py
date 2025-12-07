"""
Merlya Tools - Core tools (always active).

Includes: list_hosts, get_host, ssh_execute, ask_user, request_confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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
) -> ToolResult:
    """
    Execute a command on a host via SSH.

    Args:
        ctx: Shared context.
        host: Host name or hostname.
        command: Command to execute.
        timeout: Command timeout in seconds.
        connect_timeout: Optional connection timeout.
        elevation: Optional prepared elevation payload (from request_elevation).

    Returns:
        ToolResult with command output.
    """
    try:
        # Resolve host from inventory
        host_entry = await ctx.hosts.get_by_name(host)

        # Apply prepared elevation (brain-driven only)
        input_data = None
        elevation_used = None
        base_command = command
        elevation_needs_password = False

        # Build SSH connection options from host inventory
        from merlya.ssh import SSHConnectionOptions

        ssh_opts = SSHConnectionOptions(connect_timeout=connect_timeout)

        # Resolve jump host details from inventory if present
        if host_entry and host_entry.jump_host:
            try:
                jump_entry = await ctx.hosts.get_by_name(host_entry.jump_host)
            except Exception:  # noqa: PERF203
                jump_entry = None

            if jump_entry:
                ssh_opts.jump_host = jump_entry.hostname
                ssh_opts.jump_port = jump_entry.port
                ssh_opts.jump_username = jump_entry.username
                ssh_opts.jump_private_key = jump_entry.private_key
            else:
                ssh_opts.jump_host = host_entry.jump_host

        if elevation:
            command = elevation.get("command", command)
            base_command = elevation.get("base_command", command)
            input_data = elevation.get("input")
            elevation_used = elevation.get("method")
            elevation_needs_password = bool(elevation.get("needs_password"))

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

        result = await _run(command, input_data)

        # If elevation was password-optional and failed, retry with password
        if (
            not result.exit_code == 0
            and elevation_used
            and elevation_needs_password
            and not input_data
        ):
            try:
                permissions = await ctx.get_permissions()
                password = await ctx.ui.prompt_secret("🔑 Elevation password required")
                if password:
                    if elevation_used == "sudo_with_password":
                        command, input_data = permissions._elevate_command(  # type: ignore[attr-defined]
                            base_command, {"is_root": False}, "sudo_with_password", password
                        )
                    elif elevation_used == "su":
                        command, input_data = permissions._elevate_command(  # type: ignore[attr-defined]
                            base_command, {"is_root": False}, "su", password
                        )
                    result = await _run(command, input_data)
                    elevation_used = f"{elevation_used}_retry"
            except Exception as retry_exc:  # noqa: PERF203
                # Don't log exception details to avoid leaking password in command/input
                logger.debug(f"🔒 Elevation retry failed: {type(retry_exc).__name__}")

        return ToolResult(
            success=result.exit_code == 0,
            data={
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "host": host,
                "command": command[:50] + "..." if len(command) > 50 else command,
                "elevation": elevation_used,
            },
            error=result.stderr if result.exit_code != 0 else None,
        )

    except Exception as e:
        logger.error(f"SSH execution failed: {e}")
        return ToolResult(
            success=False,
            data={"host": host, "command": command[:50]},
            error=str(e),
        )


def _ensure_callbacks(ctx: "SharedContext", ssh_pool: Any) -> None:
    """
    Ensure MFA and passphrase callbacks are set for SSH operations.

    Uses blocking prompts in background threads to avoid event-loop conflicts.
    """
    import concurrent.futures
    import asyncio as _asyncio

    if hasattr(ssh_pool, "has_passphrase_callback") and not ssh_pool.has_passphrase_callback():
        def passphrase_cb(key_path: str) -> str:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: _asyncio.run(ctx.ui.prompt_secret(f"🔐 Passphrase for {key_path}")))
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

    return await _rc(*args, **kwargs)


async def request_elevation(*args: Any, **kwargs: Any) -> ToolResult:  # pragma: no cover - shim
    from merlya.tools.interaction import request_elevation as _re

    return await _re(*args, **kwargs)


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
