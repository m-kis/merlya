"""
Merlya Agent - Tool registration helpers.

Registers core/system/file/security tools on a PydanticAI agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_files import register_file_tools
from merlya.agent.tools_mcp import register_mcp_tools
from merlya.agent.tools_security import register_security_tools
from merlya.agent.tools_system import register_system_tools
from merlya.agent.tools_web import register_web_tools

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies, AgentResponse
else:
    AgentDependencies = Any  # type: ignore
    AgentResponse = Any  # type: ignore


def register_all_tools(agent: Agent[Any, Any]) -> None:
    """Register all Merlya tools on the provided agent."""
    _register_core_tools(agent)
    register_system_tools(agent)
    register_file_tools(agent)
    register_security_tools(agent)
    register_web_tools(agent)
    register_mcp_tools(agent)


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
        elevation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a command on a host via SSH.

        IMPORTANT - ELEVATION IS AUTOMATIC:
        - Do NOT prefix commands with 'sudo' - just run the command as-is
        - If permission denied, Merlya automatically retries with elevation
        - The user will be prompted for password if needed (handled internally)

        NEVER do this:
        - ssh_execute(command="sudo systemctl restart nginx")  # WRONG
        - ssh_execute(command="echo password | sudo -S ...")   # FORBIDDEN

        CORRECT usage:
        - ssh_execute(command="systemctl restart nginx")  # Auto-elevation if needed

        Args:
            host: Host name or hostname (target machine).
            command: Command WITHOUT sudo prefix. Can contain @secret-name references.
            timeout: Command timeout in seconds (default: 60).
            via: Optional jump host/bastion to tunnel through (e.g., "bastion").
            elevation: Optional elevation data from request_elevation (rarely needed).

        Returns:
            Command output with stdout, stderr, exit_code, elevation method, and verification hint.
            When a verification hint is present, you SHOULD run the verification command to confirm
            the action succeeded (e.g., after restart, verify service is active).

        Example:
            # Simple command (auto-elevates if permission denied)
            ssh_execute(host="web-server", command="systemctl restart nginx")

            # Via bastion
            ssh_execute(host="db-server", command="df -h", via="bastion")

            # With secrets (resolved automatically)
            ssh_execute(host="db", command="mongosh -u admin -p @db-password")
        """
        from merlya.subagents.timeout import touch_activity
        from merlya.tools.core import ssh_execute as _ssh_execute
        from merlya.tools.core.security import mask_sensitive_command
        from merlya.tools.core.verification import get_verification_hint

        via_info = f" via {via}" if via else ""
        # SECURITY: Mask sensitive data before logging
        safe_log_command = mask_sensitive_command(command)
        logger.info(f"Executing on {host}{via_info}: {safe_log_command[:50]}...")

        # Signal activity before and after SSH command
        touch_activity()

        result = await _ssh_execute(
            ctx.deps.context, host, command, timeout, via=via, elevation=elevation
        )

        # Signal activity after command completes
        touch_activity()

        if not result.success and result.error and "circuit breaker open" in result.error.lower():
            raise ModelRetry(
                "🔌 Circuit breaker open: too many SSH failures for this host. "
                "STOP issuing more ssh_execute calls to this host, wait for the retry window or reset the circuit."
            )

        response: dict[str, Any] = {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
            "elevation": result.data.get("elevation") if result.data else None,
            "via": result.data.get("via") if result.data else None,
        }

        # Add verification hint for state-changing commands
        if result.success:
            hint = get_verification_hint(command)
            if hint:
                response["verification"] = {
                    "command": hint.command,
                    "expect": hint.expect_stdout,
                    "description": hint.description,
                }

        return response

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
        host: str,
    ) -> dict[str, Any]:
        """
        Request privilege elevation explicitly (RARELY NEEDED).

        IMPORTANT: In most cases, you should NOT use this tool!
        ssh_execute() has auto_elevate=True by default - it automatically
        retries with elevation when "permission denied" occurs.

        Only use this tool when you need explicit control over the elevation
        method BEFORE attempting the command.

        Usage (when needed):
            1. Call request_elevation(host="server", command="systemctl restart nginx")
            2. Pass the result to ssh_execute:
               ssh_execute(host="server", command="systemctl restart nginx", elevation=<result>)

        NEVER construct commands like 'echo password | sudo -S' - that is FORBIDDEN.

        Args:
            command: Command that will require elevation (without sudo prefix).
            host: Target host for elevation (REQUIRED).

        Returns:
            Elevation data to pass to ssh_execute(elevation=...).
        """
        from merlya.tools.interaction import request_elevation as _request_elevation

        result = await _request_elevation(ctx.deps.context, command=command, host=host)
        if result.success:
            return cast("dict[str, Any]", result.data or {})
        raise ModelRetry(f"Failed to request elevation: {getattr(result, 'error', result.message)}")
