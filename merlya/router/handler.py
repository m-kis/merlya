"""
Merlya Router - Handler.

Simplified handler that dispatches to Orchestrator for all non-slash commands.

Architecture:
  User Input
  ├── "/" command → Slash command dispatch (handled in REPL)
  └── Free text → Orchestrator (LLM) → Delegates to specialists
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.agent.main import AgentResponse
    from merlya.agent.orchestrator import Orchestrator
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
    orchestrator: Orchestrator,
    user_input: str,
) -> HandlerResponse:
    """
    Handle a user message by delegating to the Orchestrator.

    This is the main entry point for processing free text user input.
    Slash commands are handled separately in the REPL.

    Flow:
    1. Expand @ mentions (variables, hosts)
    2. Send to Orchestrator
    3. Return formatted response

    Args:
        ctx: Shared context.
        orchestrator: Orchestrator instance.
        user_input: User input text.

    Returns:
        HandlerResponse with the result.
    """
    logger.debug(f"🤖 Processing with Orchestrator: {user_input[:50]}...")

    try:
        # Process with orchestrator
        result = await orchestrator.process(user_input)

        # Format response
        return HandlerResponse(
            message=result.message,
            actions_taken=result.actions_summary or None,
            suggestions=None,
            handled_by="orchestrator",
            raw_data={
                "delegations": result.delegations,
            }
            if result.delegations
            else None,
        )

    except Exception as e:
        logger.error(f"❌ Handler error: {e}")
        return HandlerResponse(
            message=f"Error processing request: {e}",
            actions_taken=None,
            suggestions=[ctx.t("suggestions.try_again")],
            handled_by="error",
        )


# =============================================================================
# Backward Compatibility - Legacy exports
# =============================================================================

# For code that still imports these, provide minimal stubs
# TODO: Remove after migration is complete


async def handle_user_message(
    ctx: SharedContext,
    agent: object,
    user_input: str,
    route_result: object,
) -> HandlerResponse:
    """
    Legacy handler - DEPRECATED.

    This function is kept for backward compatibility.
    New code should use handle_message() with Orchestrator.
    """
    logger.warning("⚠️ handle_user_message is deprecated, use handle_message instead")

    # Try to use orchestrator if available in context
    orchestrator = getattr(ctx, "_orchestrator", None)
    if orchestrator:
        return await handle_message(ctx, orchestrator, user_input)

    # Fallback to old agent if available
    if hasattr(agent, "run"):
        response: AgentResponse = await agent.run(user_input, route_result)
        return HandlerResponse(
            message=response.message,
            actions_taken=response.actions_taken,
            suggestions=response.suggestions,
            handled_by="agent_legacy",
        )

    return HandlerResponse(
        message="No handler available",
        handled_by="error",
    )


async def handle_fast_path(
    ctx: SharedContext,
    _route_result: object,
) -> HandlerResponse:
    """
    Legacy fast path handler - DEPRECATED.

    Fast path operations are now handled by slash commands.
    This stub returns an error directing to slash commands.
    """
    logger.warning("⚠️ handle_fast_path is deprecated, use slash commands instead")
    return HandlerResponse(
        message=ctx.t("errors.use_slash_commands"),
        handled_by="deprecated",
        suggestions=["/hosts", "/vars", "/help"],
    )


async def handle_skill_flow(
    _ctx: SharedContext,
    _user_input: str,
    _route_result: object,
) -> HandlerResponse | None:
    """
    Legacy skill handler - DEPRECATED.

    Skills have been removed. Returns None to indicate no skill handled the request.
    """
    logger.debug("⚠️ handle_skill_flow is deprecated, skills removed")
    return None


async def handle_agent(
    ctx: SharedContext,
    agent: object,
    user_input: str,
    route_result: object,
) -> HandlerResponse:
    """
    Legacy agent handler - DEPRECATED.

    Redirects to handle_user_message for backward compatibility.
    """
    return await handle_user_message(ctx, agent, user_input, route_result)
