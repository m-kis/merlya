"""
Merlya Agent - Tool registration helpers.

Registers core/system/file/security tools on a PydanticAI agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_common import check_recoverable_error
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
        # Return error info instead of retrying (system error, not recoverable)
        return {"hosts": [], "count": 0, "error": result.error}

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

        # VALIDATION: Block SSH commands - must use ssh_execute instead
        cmd_lower = command.strip().lower()
        ssh_patterns = ["ssh ", "ssh\t", "sshpass "]
        if any(cmd_lower.startswith(p) for p in ssh_patterns) or " | ssh " in cmd_lower:
            raise ModelRetry(
                "❌ WRONG TOOL: Use ssh_execute() for remote hosts, not bash('ssh ...')!\n"
                "CORRECT: ssh_execute(host='192.168.1.7', command='ls -la')\n"
                "With sudo: ssh_execute(host='192.168.1.7', command='sudo ls -la')\n"
                "With password: request_credentials(service='sudo', host='...') first, "
                "then ssh_execute(host='...', command='sudo -S ...', stdin='@sudo:HOST:password')"
            )

        # Check for loop BEFORE recording (prevents executing duplicate commands)
        # Return soft error instead of ModelRetry to avoid crashes when retries exhausted
        would_loop, reason = ctx.deps.tracker.would_loop("local", command)
        if would_loop:
            logger.warning(f"🛑 Loop prevented for bash: {reason}")
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "loop_detected": True,
                "error": f"🛑 LOOP DETECTED: {reason}\n"
                "You have repeated this command too many times. "
                "Try a DIFFERENT approach or report your findings to the user.",
            }

        ctx.deps.tracker.record("local", command)

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
        stdin: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a command on a host via SSH.

        Args:
            host: Target machine IP or hostname (e.g., "192.168.1.7", "webserver").
                  This is the MACHINE to connect to, NOT a password reference!
            command: Command to execute. Add sudo/doas/su prefix if elevation needed.
            timeout: Command timeout in seconds (default: 60).
            via: Jump host/bastion for tunneling.
            stdin: Password for su/sudo -S as @service:host:password reference.
                   Format: @sudo:192.168.1.7:password or @root:hostname:password
                   IMPORTANT: Call request_credentials(service='sudo', host='...') FIRST!

        PRIVILEGE ELEVATION:

        ⚠️ FIRST: Check get_host(name='...') → elevation_method field!
        - "sudo" or "sudo-S" → use sudo
        - "su" → use su -c (NOT sudo!)
        - None → try sudo first

        If elevation_method="sudo" or None:
        1. Try: ssh_execute(host="X", command="sudo cmd")
        2. If password needed: request_credentials(service="sudo", host="X")
        3. Then: ssh_execute(host="X", command="sudo -S cmd", stdin="@sudo:X:password")

        If elevation_method="su":
        1. request_credentials(service="root", host="X")
        2. ssh_execute(host="X", command="su -c 'cmd'", stdin="@root:X:password")

        ⚠️ COMMON MISTAKE - DON'T DO THIS:
        - ssh_execute(host="@secret-sudo", ...) ← WRONG! host must be the machine IP/name!

        Returns:
            Command output with stdout, stderr, exit_code, and verification hint.
        """
        from merlya.subagents.timeout import touch_activity
        from merlya.tools.core import ssh_execute as _ssh_execute
        from merlya.tools.core.security import mask_sensitive_command
        from merlya.tools.core.verification import get_verification_hint

        # VALIDATION: Catch common LLM mistake of passing password reference as host
        if host.startswith("@") and any(
            kw in host.lower() for kw in ["secret", "password", "sudo", "root", "cred"]
        ):
            raise ModelRetry(
                f"❌ WRONG: '{host}' is a password reference, not a host!\n"
                "host = machine IP/name (e.g., '192.168.1.7')\n"
                "stdin = password reference (e.g., '@secret-sudo')\n"
                "CORRECT: ssh_execute(host='192.168.1.7', command='sudo -S cmd', stdin='@secret-sudo')"
            )

        # VALIDATION: Catch 'sudo -S' without stdin parameter
        # Note: -S flag can be uppercase or lowercase, and can appear in various positions
        has_sudo_s = (
            "sudo -S " in command
            or "sudo -S" in command
            or ("-S" in command and "sudo" in command.lower())
        )
        has_su = command.strip().startswith("su ") or " su -c" in command.lower()
        needs_stdin = has_sudo_s or has_su

        if needs_stdin and not stdin:
            raise ModelRetry(
                f"❌ MISSING stdin! You used 'sudo -S' or 'su' but didn't provide the password.\n"
                f"REQUIRED: ssh_execute(host='{host}', command='{command[:40]}...', "
                f"stdin='@sudo:{host}:password')\n"
                f"If you haven't collected credentials yet, first call:\n"
                f"request_credentials(service='sudo', host='{host}')"
            )

        via_info = f" via {via}" if via else ""
        # SECURITY: Mask sensitive data before logging
        safe_log_command = mask_sensitive_command(command)
        logger.info(f"Executing on {host}{via_info}: {safe_log_command[:50]}...")

        # Check for loop BEFORE recording (prevents executing duplicate commands)
        # Return soft error instead of ModelRetry to avoid crashes when retries exhausted
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            logger.warning(f"🛑 Loop prevented for {host}: {reason}")
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "loop_detected": True,
                "error": f"🛑 LOOP DETECTED: {reason}\n"
                "You have repeated this command too many times on this host. "
                "Try a DIFFERENT approach or report your findings to the user.",
            }

        ctx.deps.tracker.record(host, command)

        # Signal activity before and after SSH command
        touch_activity()

        result = await _ssh_execute(ctx.deps.context, host, command, timeout, via=via, stdin=stdin)

        # Signal activity after command completes
        touch_activity()

        # Return soft error for circuit breaker instead of ModelRetry to avoid crashes
        if not result.success and result.error and "circuit breaker open" in result.error.lower():
            logger.warning(f"🔌 Circuit breaker open for {host}")
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "circuit_breaker": True,
                "error": f"🔌 CIRCUIT BREAKER OPEN for {host}: Too many SSH failures.\n"
                "STOP trying to connect to this host. Wait for the retry window or "
                "try a different host. The connection appears unstable.",
            }

        # Check for recoverable errors (host not found, etc.)
        if not result.success and check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")

        response: dict[str, Any] = {
            "success": result.success,
            "stdout": result.data.get("stdout", "") if result.data else "",
            "stderr": result.data.get("stderr", "") if result.data else "",
            "exit_code": result.data.get("exit_code", -1) if result.data else -1,
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
            # Build explicit next_step hint for elevation services
            next_step = None
            elevation_method = bundle.values.pop("_elevation_method", "sudo")
            if bundle.service.lower() in {"sudo", "root", "su", "doas"}:
                password_ref = bundle.values.get("password", "")
                if password_ref and bundle.host:
                    # Give explicit instructions based on which method works
                    if elevation_method == "su":
                        next_step = (
                            f"NOW use ssh_execute with stdin parameter (USE su -c, NOT sudo): "
                            f"ssh_execute(host='{bundle.host}', "
                            f"command=\"su -c '<your_command>'\", "
                            f"stdin='{password_ref}')"
                        )
                    else:
                        next_step = (
                            f"NOW use ssh_execute with stdin parameter: "
                            f"ssh_execute(host='{bundle.host}', "
                            f"command='sudo -S <your_command>', "
                            f"stdin='{password_ref}')"
                        )
            return {
                "service": bundle.service,
                "host": bundle.host,
                "values": bundle.values,
                "stored": bundle.stored,
                "elevation_method": elevation_method,  # "sudo" or "su"
                "next_step": next_step,
            }
        raise ModelRetry(
            f"Failed to collect credentials: {getattr(result, 'error', result.message)}"
        )
