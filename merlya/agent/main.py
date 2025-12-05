"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent with ReAct loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.router import RouterResult


# System prompt for the main agent
SYSTEM_PROMPT = """You are Merlya, an AI-powered infrastructure assistant.

You help users manage their infrastructure by:
- Diagnosing issues on servers
- Executing commands safely
- Monitoring system health
- Providing clear explanations

Key principles:
1. Always explain what you're doing before executing commands
2. Ask for confirmation before destructive actions
3. Provide concise, actionable responses
4. Use the tools available to gather information

Available context:
- Access to hosts in the inventory via list_hosts/get_host
- SSH execution via ssh_execute
- User interaction via ask_user/request_confirmation
- System information via system tools

When a host is mentioned with @hostname, resolve it from the inventory first.
Variables are referenced with @variable_name.
"""


@dataclass
class AgentDependencies:
    """Dependencies injected into the agent."""

    context: SharedContext
    router_result: RouterResult | None = None


class AgentResponse(BaseModel):
    """Response from the agent."""

    message: str
    actions_taken: list[str] = []
    suggestions: list[str] = []


def create_agent(
    model: str = "anthropic:claude-3-5-sonnet-latest",
) -> Agent[AgentDependencies, AgentResponse]:
    """
    Create the main Merlya agent.

    Args:
        model: Model to use (PydanticAI format).

    Returns:
        Configured Agent instance.
    """
    agent = Agent(
        model,
        deps_type=AgentDependencies,
        output_type=AgentResponse,
        system_prompt=SYSTEM_PROMPT,
        defer_model_check=True,  # Allow dynamic model names
    )

    # Register core tools
    _register_core_tools(agent)

    # Register system tools
    _register_system_tools(agent)

    # Register file tools
    _register_file_tools(agent)

    # Register security tools
    _register_security_tools(agent)

    return agent


def _register_core_tools(agent: Agent[AgentDependencies, AgentResponse]) -> None:
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
    ) -> dict[str, Any]:
        """
        Execute a command on a host via SSH.

        Args:
            host: Host name or hostname.
            command: Command to execute.
            timeout: Command timeout in seconds.

        Returns:
            Command output with stdout, stderr, and exit_code.
        """
        from merlya.tools.core import ssh_execute as _ssh_execute

        logger.info(f"Executing on {host}: {command[:50]}...")
        result = await _ssh_execute(ctx.deps.context, host, command, timeout)
        return {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
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
    async def request_confirmation(
        ctx: RunContext[AgentDependencies],
        action: str,
        risk_level: str = "moderate",
    ) -> bool:
        """
        Request user confirmation before an action.

        Args:
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


def _register_system_tools(agent: Agent[AgentDependencies, AgentResponse]) -> None:
    """Register system tools with the agent."""

    @agent.tool
    async def get_system_info(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Get system information from a host.

        Args:
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


def _register_file_tools(agent: Agent[AgentDependencies, AgentResponse]) -> None:
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


def _register_security_tools(agent: Agent[AgentDependencies, AgentResponse]) -> None:
    """Register security tools with the agent."""

    @agent.tool
    async def check_open_ports(
        ctx: RunContext[AgentDependencies],
        host: str,
        include_established: bool = False,
    ) -> dict[str, Any]:
        """
        Check open ports on a host.

        Args:
            host: Host name.
            include_established: Include established connections.

        Returns:
            List of open ports with process info.
        """
        from merlya.tools.security import check_open_ports as _check_open_ports

        result = await _check_open_ports(
            ctx.deps.context, host, include_established=include_established
        )
        if result.success:
            return {"ports": result.data, "severity": result.severity}
        return {"error": result.error}

    @agent.tool
    async def audit_ssh_keys(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Audit SSH keys on a host.

        Args:
            host: Host name.

        Returns:
            SSH key audit results with security issues.
        """
        from merlya.tools.security import audit_ssh_keys as _audit_ssh_keys

        result = await _audit_ssh_keys(ctx.deps.context, host)
        if result.success:
            return {"audit": result.data, "severity": result.severity}
        return {"error": result.error}

    @agent.tool
    async def check_security_config(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Check security configuration on a host.

        Args:
            host: Host name.

        Returns:
            Security configuration audit with issues.
        """
        from merlya.tools.security import check_security_config as _check_security_config

        result = await _check_security_config(ctx.deps.context, host)
        if result.success:
            return {"config": result.data, "severity": result.severity}
        return {"error": result.error}

    @agent.tool
    async def check_users(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Audit user accounts on a host.

        Args:
            host: Host name.

        Returns:
            User audit with security issues.
        """
        from merlya.tools.security import check_users as _check_users

        result = await _check_users(ctx.deps.context, host)
        if result.success:
            return {"users": result.data, "severity": result.severity}
        return {"error": result.error}

    @agent.tool
    async def check_sudo_config(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> dict[str, Any]:
        """
        Audit sudo configuration on a host.

        Args:
            host: Host name.

        Returns:
            Sudo audit with security issues.
        """
        from merlya.tools.security import check_sudo_config as _check_sudo_config

        result = await _check_sudo_config(ctx.deps.context, host)
        if result.success:
            return {"sudo": result.data, "severity": result.severity}
        return {"error": result.error}


class MerlyaAgent:
    """
    Main Merlya agent wrapper.

    Handles agent lifecycle and message processing.
    """

    def __init__(
        self,
        context: SharedContext,
        model: str = "anthropic:claude-3-5-sonnet-latest",
    ) -> None:
        """
        Initialize agent.

        Args:
            context: Shared context.
            model: Model to use.
        """
        self.context = context
        self.model = model
        self._agent = create_agent(model)
        self._history: list[dict[str, str]] = []

    async def run(
        self,
        user_input: str,
        router_result: RouterResult | None = None,
    ) -> AgentResponse:
        """
        Process user input.

        Args:
            user_input: User message.
            router_result: Optional routing result.

        Returns:
            Agent response.
        """
        deps = AgentDependencies(
            context=self.context,
            router_result=router_result,
        )

        try:
            result = await self._agent.run(
                user_input,
                deps=deps,
                message_history=self._history,  # type: ignore[arg-type]
            )

            # Update history
            self._history.append({"role": "user", "content": user_input})
            self._history.append({"role": "assistant", "content": result.output.message})

            return result.output

        except Exception as e:
            logger.error(f"Agent error: {e}")
            return AgentResponse(
                message=f"An error occurred: {e}",
                actions_taken=[],
                suggestions=["Try rephrasing your request"],
            )

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._history.clear()
        logger.debug("Conversation history cleared")
