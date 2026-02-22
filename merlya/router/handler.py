"""
Merlya Router - Handler.

Simplified handler that dispatches to Orchestrator for all non-slash commands.

Architecture:
  User Input
  ├── "/" command → Slash command dispatch (handled in REPL)
  └── Free text → Agent (LLM)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.agent.main import AgentResponse, MerlyaAgent
    from merlya.core.context import SharedContext


@dataclass
class HandlerResponse:
    """Response from a handler.

    Attributes:
        message: Response message (markdown formatted).
        actions_taken: List of actions taken. Empty lists are preserved as lists,
                      not converted to None.
        suggestions: Optional suggestions for follow-up. Empty lists are preserved
                     as lists, not converted to None.
        handled_by: Which handler processed the request.
        raw_data: Any additional structured data.
    """

    message: str
    actions_taken: list[str] | None = None
    suggestions: list[str] | None = None
    handled_by: str = "orchestrator"
    raw_data: dict[str, Any] | None = None

    @classmethod
    def from_agent_response(cls, response: AgentResponse) -> HandlerResponse:
        """Create from AgentResponse (backward compatibility)."""
        return cls(
            message=response.message,
            actions_taken=response.actions_taken,
            suggestions=response.suggestions,
            handled_by="agent",
        )


async def handle_message(
    ctx: SharedContext,
    agent: MerlyaAgent,
    user_input: str,
) -> HandlerResponse:
    """
    Handle a user message by delegating to the MerlyaAgent.

    The agent decides DIAG vs CHANGE based on its system prompt guardrails.

    Args:
        ctx: Shared context.
        agent: MerlyaAgent instance.
        user_input: User input text.

    Returns:
        HandlerResponse with the result.
    """
    logger.debug(f"🤖 Processing with Agent: {user_input[:50]}...")

    try:
        result = await agent.run(user_input)

        return HandlerResponse(
            message=result.message,
            actions_taken=result.actions_taken or None,
            suggestions=result.suggestions or None,
            handled_by="agent",
            raw_data=None,
        )

    except Exception as e:
        logger.error(f"❌ Handler error: {e}")
        return HandlerResponse(
            message=f"Error processing request: {e}",
            actions_taken=None,
            suggestions=[ctx.t("suggestions.try_again")],
            handled_by="error",
        )
