"""
Merlya Agent Specialists - Execution agent.

Write operations with confirmation (30 tool calls max).
"""

from __future__ import annotations

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.prompts import EXECUTION_PROMPT
from merlya.agent.specialists.tools import create_bash_tool, create_ssh_tool
from merlya.config.providers import get_model_for_role, get_pydantic_model_string


async def run_execution_agent(
    deps: SpecialistDeps,
    task: str,
    usage_limits: UsageLimits | None = None,
    require_confirmation: bool = True,
) -> str:
    """
    Run the Execution agent.

    Args:
        deps: Specialist dependencies (context, tracker, etc.).
        task: Task description.
        usage_limits: Optional usage limits.
        require_confirmation: Whether to require confirmation.

    Returns:
        Agent output as string.
    """
    provider = deps.context.config.model.provider
    model_id = get_model_for_role(provider, "fast")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=SpecialistDeps,
        system_prompt=EXECUTION_PROMPT,
        defer_model_check=True,
        retries=3,
    )

    _register_tools(agent, require_confirmation)

    limits = usage_limits or UsageLimits(tool_calls_limit=30)
    prompt = f"Target: {deps.target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Execution agent error: {e}", exc_info=True)
        return "❌ Execution failed. Check the logs for details."


def _register_tools(
    agent: Agent[SpecialistDeps, str],
    require_confirmation: bool,
) -> None:
    """Register execution tools (with confirmation) using tool factories."""

    # Use tool factory for ssh_execute (write mode with HITL confirmation)
    ssh_tool = create_ssh_tool(mode="write", requires_confirmation=require_confirmation)
    agent.tool(ssh_tool, name="ssh_execute")

    # Use tool factory for bash (with confirmation for write operations)
    bash_tool = create_bash_tool(requires_confirmation=require_confirmation)
    agent.tool(bash_tool, name="bash")
