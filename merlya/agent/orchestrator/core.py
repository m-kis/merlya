"""
Merlya Agent - Orchestrator (Main Agent).

The Orchestrator is the brain of the system. It:
- Understands user intent
- Classifies and delegates to specialists
- Synthesizes results
- NEVER executes bash/ssh directly

Architecture:
  User -> Orchestrator -> Specialists (Diagnostic, Execution, Security, Query)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic_ai import Agent, ModelMessage, ModelRetry

from merlya.agent.confirmation import ConfirmationState
from merlya.agent.history import create_loop_aware_history_processor
from merlya.agent.tracker import ToolCallTracker
from merlya.config.constants import DEFAULT_MAX_HISTORY_MESSAGES
from merlya.config.providers import get_model_for_role, get_pydantic_model_string

from .delegation_tools import register_delegation_tools
from .models import OrchestratorDeps, OrchestratorResponse, SecurityError
from .prompts import ORCHESTRATOR_PROMPT
from .sanitization import sanitize_user_input

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


def create_orchestrator(
    provider: str = "openrouter",
    model_override: str | None = None,
    max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES,
) -> Agent[OrchestratorDeps, OrchestratorResponse]:
    """
    Create the Orchestrator agent.

    Args:
        provider: LLM provider name.
        model_override: Optional model override (uses provider default if None).
        max_history_messages: Maximum messages to keep in conversation history.

    Returns:
        Configured Orchestrator Agent.
    """
    # Get model for orchestrator (reasoning model)
    model_id = model_override or get_model_for_role(provider, "reasoning")
    model_string = get_pydantic_model_string(provider, model_id)

    logger.debug(f"Creating Orchestrator with model: {model_string}")

    # History processor to prevent unbounded context growth
    history_processor = create_loop_aware_history_processor(
        max_messages=max_history_messages,
        enable_loop_detection=True,
    )

    agent = Agent(
        model_string,
        deps_type=OrchestratorDeps,
        output_type=OrchestratorResponse,
        system_prompt=ORCHESTRATOR_PROMPT,
        defer_model_check=True,
        history_processors=[history_processor],
    )

    # Register delegation tools
    register_delegation_tools(agent)

    return agent


class Orchestrator:
    """
    Main Orchestrator wrapper.

    Handles orchestrator lifecycle and user request processing.
    """

    def __init__(
        self,
        context: SharedContext,
        provider: str = "openrouter",
        model_override: str | None = None,
    ) -> None:
        """
        Initialize Orchestrator.

        Args:
            context: Shared context.
            provider: LLM provider.
            model_override: Optional model override.
        """
        self.context = context
        self.provider = provider
        self.model_override = model_override
        self._agent = create_orchestrator(provider, model_override)
        self._tracker = ToolCallTracker()
        self._confirmation_state = ConfirmationState()
        self._message_history: list[ModelMessage] = []

        # Connect tracker to UI for real-time tool call visibility
        self._tracker.set_ui(context.ui)

    async def process(self, user_input: str) -> OrchestratorResponse:
        """
        Process a user request.

        Args:
            user_input: User's request.

        Returns:
            Orchestrator response.

        Note:
            SecurityError exceptions are caught internally and result in an
            OrchestratorResponse with a security-blocked message instead of being raised.
        """
        # Sanitize input for security
        try:
            sanitized = sanitize_user_input(user_input)
        except SecurityError as e:
            return OrchestratorResponse(
                message=str(e),
                delegations=[],
                actions_summary=["Security check blocked request"],
            )

        # Extract and apply credential hints from user message
        # This allows users to say "password for 192.168.1.7 is @pine-pass"
        # and have the system automatically use that secret when needed
        from merlya.tools.core.resolve import apply_credential_hints_from_message

        hints_applied = apply_credential_hints_from_message(user_input)
        if hints_applied:
            logger.debug(f"Applied {hints_applied} credential hints from user message")

        deps = OrchestratorDeps(
            context=self.context,
            tracker=self._tracker,
            confirmation_state=self._confirmation_state,
        )

        try:
            result = await self._agent.run(
                sanitized,
                deps=deps,
                message_history=self._message_history if self._message_history else None,
            )

            # Update history with ALL messages for conversation continuity
            self._message_history = result.all_messages()
            logger.debug(f"Conversation history: {len(self._message_history)} messages")

            return result.output

        except ModelRetry as e:
            logger.warning(f"Orchestrator retry: {e}")
            return OrchestratorResponse(
                message=f"J'ai besoin de plus de contexte: {e}",
                delegations=[],
                actions_summary=[],
            )

        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            return OrchestratorResponse(
                message=f"Erreur: {e}",
                delegations=[],
                actions_summary=[],
            )

    def reset(self) -> None:
        """Reset orchestrator state for new conversation."""
        self._tracker.reset()
        self._confirmation_state.reset()
        self._message_history.clear()
        # Reset conversation context
        self.context.last_remote_target = None
        logger.debug("Orchestrator state reset (history cleared)")
