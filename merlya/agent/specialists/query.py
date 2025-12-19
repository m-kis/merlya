"""
Merlya Agent Specialists - Query agent.

Fast inventory queries (15 tool calls max, no SSH).
"""

from __future__ import annotations

from typing import cast

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.prompts import QUERY_PROMPT
from merlya.agent.specialists.types import HostInfo, HostListResult
from merlya.config.providers import get_model_for_role, get_pydantic_model_string


async def run_query_agent(
    deps: SpecialistDeps,
    task: str,
    usage_limits: UsageLimits | None = None,
) -> str:
    """
    Run the Query agent.

    Args:
        deps: Specialist dependencies (context, tracker, etc.).
        task: Question to answer.
        usage_limits: Optional usage limits.

    Returns:
        Agent output as string.
    """
    provider = deps.context.config.model.provider
    model_id = get_model_for_role(provider, "fast")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=SpecialistDeps,
        system_prompt=QUERY_PROMPT,
        defer_model_check=True,
        retries=3,
    )

    _register_tools(agent)

    limits = usage_limits or UsageLimits(tool_calls_limit=15)

    try:
        result = await agent.run(task, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Query agent error: {e}", exc_info=True)
        return "❌ La requête a rencontré une erreur. Vérifiez les logs."


def _register_tools(agent: Agent[SpecialistDeps, str]) -> None:
    """Register query tools (inventory only, no SSH)."""

    @agent.tool
    async def list_hosts(
        ctx: RunContext[SpecialistDeps],
        tag: str | None = None,
        limit: int = 20,
    ) -> HostListResult:
        """List hosts from inventory."""
        from merlya.tools.core import list_hosts as _list_hosts

        result = await _list_hosts(ctx.deps.context, tag=tag, limit=limit)
        if result.success:
            # Convert to HostInfo list
            hosts = [cast("HostInfo", h) for h in result.data] if result.data else []
            return HostListResult(hosts=hosts, count=len(hosts))
        return HostListResult(hosts=[], count=0, error=result.error or "")

    @agent.tool
    async def get_host(
        ctx: RunContext[SpecialistDeps],
        name: str,
    ) -> HostInfo:
        """Get details about a specific host."""
        from merlya.tools.core import get_host as _get_host

        result = await _get_host(ctx.deps.context, name)
        if result.success and result.data:
            return cast("HostInfo", result.data)
        raise ModelRetry(f"Host not found: {result.error}")

    @agent.tool
    async def ask_user(
        ctx: RunContext[SpecialistDeps],
        question: str,
        choices: list[str] | None = None,
    ) -> str:
        """Ask the user a question."""
        from merlya.tools.core import ask_user as _ask_user

        result = await _ask_user(ctx.deps.context, question, choices=choices)
        if result.success:
            return cast("str", result.data) or ""
        return ""
