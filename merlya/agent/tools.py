"""
Merlya Agent - Tool registration helpers.

Registers core/system/file/security tools on a PydanticAI agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_security import register_security_tools
from merlya.agent.tools_web import register_web_tools

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies, AgentResponse
else:
    AgentDependencies = Any  # type: ignore
    AgentResponse = Any  # type: ignore


def register_all_tools(agent: Agent[Any, Any]) -> None:
    """Register all Merlya tools on the provided agent."""
    _register_core_tools(agent)
    _register_system_tools(agent)
    _register_file_tools(agent)
    register_security_tools(agent)
    register_web_tools(agent)


def _register_core_tools(agent: Agent[Any, Any]) -> None:
    """Register core tools with the agent."""

    @agent.tool
    async def list_hosts(
        ctx: RunContext[AgentDependencies],
        tag: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        List hosts from the inventory.

        Args:
            ctx: Run context.
            tag: Optional tag to filter hosts.
            limit: Maximum number of hosts to return.

        Returns:
            List of hosts with name, hostname, status, and tags.
        """
        from merlya.tools.core import list_hosts as _list_hosts

        result = await _list_hosts(ctx.deps.context, tag=tag, limit=limit)
        if result.success:
            return {"hosts": result.data, "count": len(result.data)}
        raise ModelRetry(f"Failed to list hosts: {result.error}")

    @agent.tool
    async def get_host(
        ctx: RunContext[AgentDependencies],
        name: str,
    ) -> dict[str, Any]:
        """
        Get detailed information about a specific host.

        Args:
            ctx: Run context.
            name: Host name from inventory.

        Returns:
            Host details including hostname, port, tags, and metadata.
        """
        from merlya.tools.core import get_host as _get_host

        result = await _get_host(ctx.deps.context, name)
        if result.success:
            return cast("dict[str, Any]", result.data)
        raise ModelRetry(f"Host not found: {result.error}")

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[AgentDependencies],
        host: str,
        command: str,
        timeout: int = 60,
        elevation: dict[str, Any] | None = None,
        via: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a command on a host via SSH.

        Args:
            ctx: Run context.
            host: Host name or hostname (target machine).
            command: Command to execute.
            timeout: Command timeout in seconds.
            elevation: Optional elevation payload (from request_elevation).
            via: Optional jump host/bastion to reach the target.
                 Use this when the target is not directly accessible.
                 Can be a host name from inventory (e.g., "ansible", "bastion")
                 or an IP/hostname. The connection will tunnel through this host.

        Returns:
            Command output with stdout, stderr, and exit_code.

        Example:
            To execute on a remote host via a bastion:
            ssh_execute(host="db-server", command="df -h", via="bastion")
        """
        from merlya.tools.core import ssh_execute as _ssh_execute

        router_result = getattr(ctx.deps, "router_result", None)
        if router_result and router_result.elevation_required and elevation is None:
            raise ModelRetry(
                "Elevation flagged by router. Use request_elevation to prepare the command, "
                "then pass the returned payload to ssh_execute via the 'elevation' argument."
            )

        via_info = f" via {via}" if via else ""
        logger.info(f"Executing on {host}{via_info}: {command[:50]}...")
        result = await _ssh_execute(
            ctx.deps.context, host, command, timeout, elevation=elevation, via=via
        )
        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
            "via": result.data.get("via") if result.data else None,
        }

    @agent.tool
    async def ask_user(
        ctx: RunContext[AgentDependencies],
        question: str,
        choices: list[str] | None = None,
    ) -> str:
        """
        Ask the user a question.

        Args:
            ctx: Run context.
            question: Question to ask.
            choices: Optional list of choices.

        Returns:
            User's response.
        """
        from merlya.tools.core import ask_user as _ask_user

        result = await _ask_user(ctx.deps.context, question, choices=choices)
        if result.success:
            return cast("str", result.data) or ""
        return ""

    @agent.tool
    async def request_credentials(
        ctx: RunContext[AgentDependencies],
        service: str,
        host: str | None = None,
        fields: list[str] | None = None,
        format_hint: str | None = None,
    ) -> dict[str, Any]:
        """Request credentials interactively (brain-driven)."""
        from merlya.tools.interaction import request_credentials as _request_credentials

        result = await _request_credentials(
            ctx.deps.context,
            service=service,
            host=host,
            fields=fields,
            format_hint=format_hint,
        )
        if result.success:
            bundle = result.data
            return {
                "service": bundle.service,
                "host": bundle.host,
                "values": bundle.values,
                "stored": bundle.stored,
            }
        raise ModelRetry(
            f"Failed to collect credentials: {getattr(result, 'error', result.message)}"
        )

    @agent.tool
    async def request_elevation(
        ctx: RunContext[AgentDependencies],
        command: str,
        host: str | None = None,
    ) -> dict[str, Any]:
        """Request privilege elevation (brain-driven)."""
        from merlya.tools.interaction import request_elevation as _request_elevation

        result = await _request_elevation(ctx.deps.context, command=command, host=host)
        if result.success:
            return cast("dict[str, Any]", result.data or {})
        raise ModelRetry(f"Failed to request elevation: {getattr(result, 'error', result.message)}")

    @agent.tool
    async def request_confirmation(
        ctx: RunContext[AgentDependencies],
        action: str,
        risk_level: str = "moderate",
    ) -> bool:
        """
        Request user confirmation before an action.

        Args:
            ctx: Run context.
            action: Description of the action to confirm.
            risk_level: Risk level (low, moderate, high, critical).

        Returns:
            True if user confirmed, False otherwise.
        """
        from merlya.tools.core import request_confirmation as _request_confirmation

        result = await _request_confirmation(
            ctx.deps.context,
            action,
            risk_level=risk_level,
        )
        return result.data if result.success else False


def _register_system_tools(agent: Agent[Any, Any]) -> None:
    """Register system tools with the agent."""

    @agent.tool
    async def get_system_info(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Get system information from a host.

        Args:
            ctx: Run context.
            host: Host name.

        Returns:
            System info including OS, kernel, uptime, and load.
        """
        from merlya.tools.system import get_system_info as _get_system_info

        result = await _get_system_info(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_disk_usage(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str = "/",
    ) -> dict[str, Any]:
        """
        Check disk usage on a host.

        Args:
            ctx: Run context.
            host: Host name.
            path: Filesystem path to check.

        Returns:
            Disk usage info with size, used, available, and percentage.
        """
        from merlya.tools.system import check_disk_usage as _check_disk_usage

        result = await _check_disk_usage(ctx.deps.context, host, path)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_memory(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Check memory usage on a host.

        Args:
            ctx: Run context.
            host: Host name.

        Returns:
            Memory usage info with total, used, available, and percentage.
        """
        from merlya.tools.system import check_memory as _check_memory

        result = await _check_memory(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_cpu(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Check CPU usage on a host.

        Args:
            ctx: Run context.
            host: Host name.

        Returns:
            CPU info with load averages, CPU count, and usage percentage.
        """
        from merlya.tools.system import check_cpu as _check_cpu

        result = await _check_cpu(ctx.deps.context, host)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def check_service_status(
        ctx: RunContext[AgentDependencies],
        host: str,
        service: str,
    ) -> dict[str, Any]:
        """
        Check the status of a systemd service.

        Args:
            ctx: Run context.
            host: Host name.
            service: Service name (e.g., nginx, docker, ssh).

        Returns:
            Service status info with active state and PID.
        """
        from merlya.tools.system import check_service_status as _check_service_status

        result = await _check_service_status(ctx.deps.context, host, service)
        if result.success:
            return cast("dict[str, Any]", result.data)
        return {"error": result.error}

    @agent.tool
    async def list_processes(
        ctx: RunContext[AgentDependencies],
        host: str,
        user: str | None = None,
        filter_name: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        List running processes on a host.

        Args:
            ctx: Run context.
            host: Host name.
            user: Filter by user.
            filter_name: Filter by process name.
            limit: Maximum processes to return.

        Returns:
            List of processes with user, PID, CPU, memory, and command.
        """
        from merlya.tools.system import list_processes as _list_processes

        result = await _list_processes(
            ctx.deps.context,
            host,
            user=user,
            filter_name=filter_name,
            limit=limit,
        )
        if result.success:
            return cast("list[dict[str, Any]]", result.data)
        return []


def _register_file_tools(agent: Agent[Any, Any]) -> None:
    """Register file operation tools with the agent."""

    @agent.tool
    async def read_file(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        lines: int | None = None,
        tail: bool = False,
    ) -> dict[str, Any]:
        """
        Read file content from a host.

        Args:
            ctx: Run context.
            host: Host name.
            path: File path to read.
            lines: Number of lines to read (optional).
            tail: If True, read from end of file.

        Returns:
            File content.
        """
        from merlya.tools.files import read_file as _read_file

        result = await _read_file(ctx.deps.context, host, path, lines=lines, tail=tail)
        if result.success:
            return {"content": result.data}
        return {"error": result.error}

    @agent.tool
    async def write_file(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        content: str,
        backup: bool = True,
    ) -> dict[str, Any]:
        """
        Write content to a file on a host.

        Args:
            ctx: Run context.
            host: Host name.
            path: File path.
            content: Content to write.
            backup: Create backup before writing.

        Returns:
            Operation result.
        """
        from merlya.tools.files import write_file as _write_file

        result = await _write_file(ctx.deps.context, host, path, content, backup=backup)
        if result.success:
            return {"success": True, "message": result.data}
        return {"success": False, "error": result.error}

    @agent.tool
    async def list_directory(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        all_files: bool = False,
        long_format: bool = False,
    ) -> dict[str, Any]:
        """
        List directory contents on a host.

        Args:
            ctx: Run context.
            host: Host name.
            path: Directory path.
            all_files: Include hidden files.
            long_format: Use detailed listing.

        Returns:
            Directory listing.
        """
        from merlya.tools.files import list_directory as _list_directory

        result = await _list_directory(
            ctx.deps.context, host, path, all_files=all_files, long_format=long_format
        )
        if result.success:
            return {"entries": result.data}
        return {"error": result.error}

    @agent.tool
    async def search_files(
        ctx: RunContext[AgentDependencies],
        host: str,
        path: str,
        pattern: str,
        file_type: str | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """
        Search for files on a host.

        Args:
            ctx: Run context.
            host: Host name.
            path: Search path.
            pattern: File name pattern (e.g., "*.log").
            file_type: Type filter (f=file, d=directory).
            max_depth: Maximum search depth.

        Returns:
            List of matching files.
        """
        from merlya.tools.files import search_files as _search_files

        result = await _search_files(
            ctx.deps.context, host, path, pattern, file_type=file_type, max_depth=max_depth
        )
        if result.success:
            return {"files": result.data, "count": len(result.data) if result.data else 0}
        return {"error": result.error}
