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
    _register_mcp_tools(agent)


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
            tag: Optional tag to filter hosts (e.g., "web", "database").
            limit: Maximum number of hosts to return (default: 20).

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
            name: Host name from inventory (e.g., "myserver", "db-prod").

        Returns:
            Host details including hostname, port, tags, and metadata.
        """
        from merlya.tools.core import get_host as _get_host

        result = await _get_host(ctx.deps.context, name)
        if result.success:
            return cast("dict[str, Any]", result.data)
        raise ModelRetry(f"Host not found: {result.error}")

    @agent.tool
    async def bash(
        ctx: RunContext[AgentDependencies],
        command: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """
        Execute a command locally on your machine.

        Use this tool for local operations:
        - kubectl, aws, gcloud, az CLI commands
        - docker commands
        - Local file checks
        - Any CLI tool installed locally

        This is your UNIVERSAL FALLBACK when no specific tool exists.

        Args:
            command: Command to execute (e.g., "kubectl get pods", "aws s3 ls").
            timeout: Command timeout in seconds (default: 60).

        Returns:
            Command output with stdout, stderr, and exit_code.

        Example:
            bash(command="kubectl get pods -n production")
            bash(command="aws eks list-clusters")
            bash(command="docker ps")
        """
        from merlya.subagents.timeout import touch_activity
        from merlya.tools.core import bash_execute as _bash_execute

        logger.info(f"🖥️ Running locally: {command[:60]}...")

        touch_activity()
        result = await _bash_execute(ctx.deps.context, command, timeout)
        touch_activity()

        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        }

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[AgentDependencies],
        host: str,
        command: str,
        timeout: int = 60,
        via: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a command on a host via SSH.

        Features handled automatically by Merlya:
        - Secret resolution: @secret-name in commands are resolved from keyring
        - Auto-elevation: Permission denied errors trigger automatic elevation retry

        Args:
            host: Host name or hostname (target machine).
            command: Command to execute. Can contain @secret-name references.
            timeout: Command timeout in seconds (default: 60).
            via: Optional jump host/bastion to tunnel through (e.g., "bastion").

        Returns:
            Command output with stdout, stderr, and exit_code.

        Example:
            # Execute on a remote host via a bastion
            ssh_execute(host="db-server", command="df -h", via="bastion")

            # Use secrets in commands (resolved automatically)
            ssh_execute(host="db", command="mongosh -u admin -p @db-password")
        """
        from merlya.subagents.timeout import touch_activity
        from merlya.tools.core import ssh_execute as _ssh_execute

        via_info = f" via {via}" if via else ""
        # Note: command may contain @secret-name, resolved in _ssh_execute
        # Logs will show @secret-name, not actual values
        logger.info(f"Executing on {host}{via_info}: {command[:50]}...")

        # Signal activity before and after SSH command
        touch_activity()

        result = await _ssh_execute(ctx.deps.context, host, command, timeout, via=via)

        # Signal activity after command completes
        touch_activity()

        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
            "elevation": result.data.get("elevation") if result.data else None,
            "via": result.data.get("via") if result.data else None,
        }

    @agent.tool
    async def ask_user(
        ctx: RunContext[AgentDependencies],
        question: str,
        choices: list[str] | None = None,
    ) -> str:
        """
        Ask the user a question and wait for response.

        Args:
            question: Question to ask the user.
            choices: Optional list of choices to present (e.g., ["yes", "no"]).

        Returns:
            User's response as string.
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
        """
        Request credentials from the user interactively.

        Use this tool when authentication fails and you need username/password
        or API keys from the user.

        Args:
            service: Service name requiring credentials (e.g., "mongodb", "api").
            host: Target host for these credentials (optional).
            fields: List of field names to collect (default: ["username", "password"]).
            format_hint: Hint about expected format (e.g., "JSON key file").

        Returns:
            Collected credentials with service, host, and values.
        """
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
        """
        Request privilege elevation from the user.

        Use this tool when a command fails with "Permission denied" and you need
        sudo/su/doas access to retry.

        Args:
            command: Command that requires elevation.
            host: Target host for elevation (optional).

        Returns:
            Elevation method approved by user (e.g., "sudo", "su").
        """
        from merlya.tools.interaction import request_elevation as _request_elevation

        result = await _request_elevation(ctx.deps.context, command=command, host=host)
        if result.success:
            return cast("dict[str, Any]", result.data or {})
        raise ModelRetry(f"Failed to request elevation: {getattr(result, 'error', result.message)}")


def _register_mcp_tools(agent: Agent[Any, Any]) -> None:
    """Register MCP bridge tools."""

    @agent.tool
    async def list_mcp_tools(ctx: RunContext[AgentDependencies]) -> dict[str, Any]:
        """
        List available MCP tools from configured servers.

        MCP (Model Context Protocol) tools are external capabilities
        provided by configured MCP servers.

        Returns:
            List of available tool names and count.
        """
        manager = await ctx.deps.context.get_mcp_manager()
        tools = await manager.list_tools()
        return {"tools": [tool.name for tool in tools], "count": len(tools)}

    @agent.tool
    async def call_mcp_tool(
        ctx: RunContext[AgentDependencies],
        tool: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Call an MCP tool by name.

        Args:
            tool: Tool name in format "server.tool" (e.g., "github.list_repos").
            arguments: Arguments to pass to the tool (optional).

        Returns:
            Tool execution result.
        """
        manager = await ctx.deps.context.get_mcp_manager()
        return await manager.call_tool(tool, arguments or {})

    @agent.tool
    async def request_confirmation(
        ctx: RunContext[AgentDependencies],
        action: str,
        risk_level: str = "moderate",
    ) -> bool:
        """
        Request user confirmation before a destructive action.

        Use this tool before restart, delete, stop, or other risky operations.

        Args:
            action: Description of the action to confirm (e.g., "restart nginx service").
            risk_level: Risk level: "low", "moderate", "high", or "critical".

        Returns:
            True if user confirmed, False if declined.
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
            host: Host name from inventory.

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
            host: Host name from inventory.
            path: Filesystem path to check (default: "/").

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
            host: Host name from inventory.

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
            host: Host name from inventory.

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
            host: Host name from inventory.
            service: Service name (e.g., "nginx", "docker", "ssh").

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
            host: Host name from inventory.
            user: Filter by user name (optional).
            filter_name: Filter by process name (optional).
            limit: Maximum processes to return (default: 10).

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
            host: Host name from inventory.
            path: Absolute file path to read (e.g., "/etc/nginx/nginx.conf").
            lines: Number of lines to read (optional, reads entire file if not set).
            tail: If True, read from end of file (default: False).

        Returns:
            File content as string.
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
            host: Host name from inventory.
            path: Absolute file path to write.
            content: Content to write to the file.
            backup: Create backup before writing (default: True).

        Returns:
            Success status and message.
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
            host: Host name from inventory.
            path: Directory path to list (e.g., "/var/log").
            all_files: Include hidden files (default: False).
            long_format: Use detailed listing with permissions (default: False).

        Returns:
            List of directory entries.
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
            host: Host name from inventory.
            path: Starting directory for search (e.g., "/var/log").
            pattern: File name pattern with wildcards (e.g., "*.log", "nginx*").
            file_type: Type filter: "f" for files, "d" for directories (optional).
            max_depth: Maximum directory depth to search (optional).

        Returns:
            List of matching file paths.
        """
        from merlya.tools.files import search_files as _search_files

        result = await _search_files(
            ctx.deps.context, host, path, pattern, file_type=file_type, max_depth=max_depth
        )
        if result.success:
            return {"files": result.data, "count": len(result.data) if result.data else 0}
        return {"error": result.error}
