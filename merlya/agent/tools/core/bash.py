"""
Bash command execution tool for Merlya agent.

Provides local command execution capabilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any


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


def register(agent: Agent[Any, Any]) -> None:
    """Register bash tool on agent."""
    agent.tool(bash)
