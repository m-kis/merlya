"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent with ReAct loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from merlya.agent.agent_factory import create_agent
from merlya.agent.tracker import ToolCallTracker
from merlya.config.constants import (
    DEFAULT_REQUEST_LIMIT,
    DEFAULT_TOOL_CALLS_LIMIT,
    TITLE_MAX_LENGTH,
)
from merlya.config.provider_env import ensure_provider_env

# Re-export create_agent from agent_factory
__all__ = ["AgentDependencies", "AgentResponse", "MerlyaAgent", "create_agent"]

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Conversation
    from merlya.router import RouterResult


@dataclass
class AgentDependencies:
    """Dependencies injected into the agent."""

    context: SharedContext
    router_result: RouterResult | None = None
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    user_input: str = ""  # Original user request for context


class AgentResponse(BaseModel):
    """Response from the agent."""

    message: str
    actions_taken: list[str] = []
    suggestions: list[str] = []


class MerlyaAgent:
    """
    Main Merlya agent wrapper.

    Handles agent lifecycle and message processing.
    """

    def __init__(
        self,
        context: SharedContext,
        model: str = "anthropic:claude-3-5-sonnet-latest",
    ) -> None:
        """
        Initialize agent.

        Args:
            context: Shared context.
            model: Model to use.
        """
        self.context = context
        ensure_provider_env(self.context.config)
        self.model = model
        self._agent = create_agent(model)
        self._message_history: list[ModelMessage] = []
        self._active_conversation: Conversation | None = None

    async def run(
        self,
        user_input: str,
        router_result: RouterResult | None = None,
        usage_limits: UsageLimits | None = None,
    ) -> AgentResponse:
        """
        Process user input until task completion.

        Args:
            user_input: User message.
            router_result: Optional routing result.
            usage_limits: Optional limits on token/request usage.

        Returns:
            Agent response.

        Note:
            The agent runs until completion using the ReAct loop pattern.
            Loop detection (history.py) prevents unproductive behavior.
        """
        limits = self._compute_usage_limits(router_result, usage_limits)

        try:
            if self._active_conversation is None:
                self._active_conversation = await self._create_conversation(user_input)

            self._apply_credential_hints(user_input)
            await self._mark_unresolved_hosts(router_result)

            deps = AgentDependencies(
                context=self.context,
                router_result=router_result,
                user_input=user_input,
            )
            return await self._run_agent_with_errors(user_input, deps, limits)

        except asyncio.CancelledError:
            logger.debug("Agent task cancelled")
            await self._persist_history()
            raise
        except Exception as e:
            logger.error(f"Agent error: {e}")
            await self._persist_history()
            return AgentResponse(
                message=f"An error occurred: {e}",
                actions_taken=[],
                suggestions=["Try rephrasing your request"],
            )

    def _compute_usage_limits(
        self,
        router_result: RouterResult | None,
        usage_limits: UsageLimits | None,
    ) -> UsageLimits:
        """Compute usage limits from router result or defaults."""
        if usage_limits is not None:
            return usage_limits

        if router_result is not None:
            request_limit = router_result.request_limit
            tool_limit = router_result.tool_calls_limit
        else:
            request_limit = DEFAULT_REQUEST_LIMIT
            tool_limit = DEFAULT_TOOL_CALLS_LIMIT

        return UsageLimits(request_limit=request_limit, tool_calls_limit=tool_limit)

    def _apply_credential_hints(self, user_input: str) -> None:
        """Extract and apply credential hints from user message."""
        from merlya.tools.core.resolve import apply_credential_hints_from_message

        hints_applied = apply_credential_hints_from_message(user_input)
        if hints_applied:
            logger.debug(f"🔑 Applied {hints_applied} credential hints from user message")

    async def _mark_unresolved_hosts(self, router_result: RouterResult | None) -> None:
        """Mark hosts not in inventory for proactive discovery."""
        if not router_result or not router_result.entities.get("hosts"):
            return

        unresolved = []
        for host_name in router_result.entities["hosts"]:
            host_entry = await self.context.hosts.get_by_name(host_name)
            if not host_entry:
                unresolved.append(host_name)

        if unresolved:
            router_result.unresolved_hosts = unresolved
            logger.debug(f"🔍 Unresolved hosts (not in inventory): {unresolved}")

    async def _run_agent_with_errors(
        self,
        user_input: str,
        deps: AgentDependencies,
        usage_limits: UsageLimits,
    ) -> AgentResponse:
        """Execute agent run with error handling."""
        from pydantic_ai.settings import ModelSettings

        timeout = self.context.config.model.get_timeout()
        timeout_value = float(timeout) if timeout is not None else 90.0
        model_settings = ModelSettings(timeout=timeout_value)
        logger.debug(f"🕐 LLM request timeout: {timeout_value}s")

        try:
            result = await self._agent.run(
                user_input,
                deps=deps,
                message_history=self._message_history if self._message_history else None,
                usage_limits=usage_limits,
                model_settings=model_settings,
            )
        except UsageLimitExceeded as e:
            logger.warning(f"⚠️ Failsafe limit reached: {e}")
            await self._persist_history()
            return AgentResponse(
                message=f"Task too complex - safety limit reached: {e}",
                actions_taken=[],
                suggestions=["Break the task into smaller steps"],
            )
        except UnexpectedModelBehavior as e:
            return await self._handle_model_behavior_error(e)

        self._message_history = result.all_messages()
        await self._persist_history()
        return result.output

    async def _handle_model_behavior_error(self, e: UnexpectedModelBehavior) -> AgentResponse:
        """Handle UnexpectedModelBehavior exceptions with helpful messages."""
        error_msg = str(e)
        logger.warning(f"⚠️ Model behavior issue: {error_msg}")
        await self._persist_history()

        if "exceeded max retries" in error_msg.lower():
            return AgentResponse(
                message=(
                    "⚠️ Encountered repeated issues with this command. "
                    "This may be due to:\n"
                    "- Authentication errors (wrong password)\n"
                    "- Incompatible elevation method (sudo vs su)\n"
                    "- SSH connection issues\n\n"
                    "Try rephrasing the task or check the credentials."
                ),
                actions_taken=[],
                suggestions=[
                    "Check credentials with 'merlya hosts show <host>'",
                    "Try a different elevation method",
                ],
            )

        return AgentResponse(
            message=f"⚠️ Unexpected behavior: {error_msg}",
            actions_taken=[],
            suggestions=["Rephrase the request"],
        )

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._message_history.clear()
        self._active_conversation = None
        logger.debug("Conversation history cleared")

    async def _create_conversation(self, title_seed: str | None = None) -> Conversation:
        """Create and persist a new conversation with optional title."""
        from merlya.persistence.models import Conversation

        title = self._derive_title(title_seed)
        conv = Conversation(title=title, messages=[])
        try:
            conv = await self.context.conversations.create(conv)
        except Exception as e:
            logger.warning(f"Failed to persist conversation start: {e}")
        return conv

    async def _persist_history(self) -> None:
        """Persist current history into the active conversation."""
        if not self._active_conversation:
            return

        # Serialize ModelMessage objects to JSON-compatible format
        # This preserves tool calls and all message metadata
        self._active_conversation.messages = ModelMessagesTypeAdapter.dump_python(
            self._message_history, mode="json"
        )

        if not self._active_conversation.title:
            self._active_conversation.title = self._derive_title(self._extract_first_user_message())

        try:
            await self.context.conversations.update(self._active_conversation)
        except Exception as e:
            logger.warning(f"Failed to persist conversation history: {e}")

    def load_conversation(self, conv: Conversation) -> None:
        """Load an existing conversation into the agent history."""
        self._active_conversation = conv

        # Deserialize JSON messages back to ModelMessage objects
        if conv.messages:
            try:
                self._message_history = ModelMessagesTypeAdapter.validate_python(conv.messages)
            except Exception as e:
                logger.warning(f"Failed to deserialize conversation history: {e}")
                self._message_history = []
        else:
            self._message_history = []

        logger.debug(
            f"Loaded conversation {conv.id[:8]} with {len(self._message_history)} messages"
        )

    def _extract_first_user_message(self) -> str | None:
        """Extract text content from the first user message."""
        from pydantic_ai import ModelRequest, UserPromptPart

        for msg in self._message_history:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart) and part.content:
                        # Handle both string and list content
                        if isinstance(part.content, str):
                            return part.content
                        # For list content, find the first text
                        for item in part.content:
                            if isinstance(item, str):
                                return item
        return None

    def _derive_title(self, seed: str | None) -> str:
        """Generate a short title from the first user message."""
        if not seed:
            return "Conversation"
        text = seed.strip().splitlines()[0]
        return (text[:TITLE_MAX_LENGTH] + "...") if len(text) > TITLE_MAX_LENGTH else text
