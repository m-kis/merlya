"""
Merlya Agent Specialists - Diagnostic agent.

Read-only investigation agent (40 tool calls max).
"""

from __future__ import annotations

import shlex

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.prompts import DIAGNOSTIC_PROMPT
from merlya.agent.specialists.tools import create_bash_tool, create_ssh_tool
from merlya.agent.specialists.types import FileReadResult
from merlya.config.providers import get_model_for_role, get_pydantic_model_string


async def run_diagnostic_agent(
    deps: SpecialistDeps,
    task: str,
    usage_limits: UsageLimits | None = None,
) -> str:
    """
    Run the Diagnostic agent.

    Args:
        deps: Specialist dependencies (context, tracker, etc.).
        task: Task description.
        usage_limits: Optional usage limits.

    Returns:
        Agent output as string.
    """
    provider = deps.context.config.model.provider
    model_id = get_model_for_role(provider, "reasoning")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=SpecialistDeps,
        system_prompt=DIAGNOSTIC_PROMPT,
        defer_model_check=True,
        retries=3,
    )

    _register_tools(agent)

    limits = usage_limits or UsageLimits(tool_calls_limit=40)
    prompt = f"Target: {deps.target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Diagnostic agent error: {e}", exc_info=True)
        return "❌ The investigation encountered an error. Check the logs."


def _register_tools(agent: Agent[SpecialistDeps, str]) -> None:
    """Register diagnostic tools (read-only) using tool factories."""

    # Use tool factory for ssh_execute (read-only mode)
    ssh_tool = create_ssh_tool(mode="read", requires_confirmation=False)
    agent.tool(ssh_tool, name="ssh_execute")

    # Use tool factory for bash (no confirmation for read-only)
    bash_tool = create_bash_tool(requires_confirmation=False)
    agent.tool(bash_tool, name="bash")

    @agent.tool
    async def read_file(
        ctx: RunContext[SpecialistDeps],
        host: str,
        path: str,
    ) -> FileReadResult:
        """Read a file from a remote host."""
        from merlya.tools.core import ssh_execute as _ssh_execute

        quoted_path = shlex.quote(path)
        command = f"cat -- {quoted_path}"

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT approach.")

        ctx.deps.tracker.record(host, command)

        result = await _ssh_execute(ctx.deps.context, host, command, timeout=30)
        return FileReadResult(
            success=result.success,
            content=result.data.get("stdout", "") if result.data else "",
            error=result.data.get("stderr", "") if result.data else "",
        )
