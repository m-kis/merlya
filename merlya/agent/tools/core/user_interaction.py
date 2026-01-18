"""
User interaction tool for Merlya agent.

Provides the ability to ask questions to the user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, RunContext  # noqa: TC002 - required at runtime

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any


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


def register(agent: Agent[AgentDependencies, Any]) -> None:
    """Register user interaction tool on agent."""
    agent.tool(ask_user)
