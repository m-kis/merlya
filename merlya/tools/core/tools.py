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
    ctx: "SharedContext",
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
    ctx: "SharedContext",
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
    ctx: "SharedContext",
    host: str,
    command: str,
    timeout: int = 60,
) -> ToolResult:
    """
    Execute a command on a host via SSH.

    Args:
        ctx: Shared context.
        host: Host name or hostname.
        command: Command to execute.
        timeout: Command timeout in seconds.

    Returns:
        ToolResult with command output.
    """
    try:
        # Resolve host from inventory
        host_entry = await ctx.hosts.get_by_name(host)

        # Get SSH pool
        ssh_pool = await ctx.get_ssh_pool()

        if host_entry:
            stdout, stderr, exit_code = await ssh_pool.execute(
                host=host_entry.hostname,
                command=command,
                timeout=timeout,
                port=host_entry.port,
                username=host_entry.username,
                private_key=host_entry.private_key,
                jump_host=host_entry.jump_host,
            )
        else:
            # Direct hostname
            stdout, stderr, exit_code = await ssh_pool.execute(
                host=host,
                command=command,
                timeout=timeout,
            )

        return ToolResult(
            success=exit_code == 0,
            data={
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "host": host,
                "command": command[:50] + "..." if len(command) > 50 else command,
            },
            error=stderr if exit_code != 0 else None,
        )

    except Exception as e:
        logger.error(f"SSH execution failed: {e}")
        return ToolResult(
            success=False,
            data={"host": host, "command": command[:50]},
            error=str(e),
        )


async def ask_user(
    ctx: "SharedContext",
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
    ctx: "SharedContext",
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


async def get_variable(
    ctx: "SharedContext",
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
    ctx: "SharedContext",
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
