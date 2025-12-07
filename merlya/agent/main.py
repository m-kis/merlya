"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent with ReAct loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel
from pydantic_ai import Agent

from merlya.agent.tools import register_all_tools

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Conversation
    from merlya.router import RouterResult


# System prompt for the main agent
SYSTEM_PROMPT = """You are Merlya, an AI-powered infrastructure assistant.

You help users manage their infrastructure by:
- Diagnosing issues on servers
- Executing commands safely
- Monitoring system health
- Providing clear explanations
- When authentication fails (credentials, tokens, passphrases, JSON keys), use the tool `request_credentials` to collect the needed fields.
- When you detect permission issues or the router flags elevation, use `request_elevation` before retrying commands.
- Never invent secrets; always ask the user via tools.

Key principles:
1. Always explain what you're doing before executing commands
2. Ask for confirmation before destructive actions
3. Provide concise, actionable responses
4. Use the tools available to gather information
5. If the router signals `credentials_required` or `elevation_required`, explicitly address it with the proper tool before proceeding.

Available context:
- Access to hosts in the inventory via list_hosts/get_host
- SSH execution via ssh_execute
- User interaction via ask_user/request_confirmation
- System information via system tools
- Credentials and elevation tools are available as request_credentials and request_elevation.

When a host is mentioned with @hostname, resolve it from the inventory first.
Variables are referenced with @variable_name.
"""


@dataclass
class AgentDependencies:
    """Dependencies injected into the agent."""

    context: SharedContext
    router_result: RouterResult | None = None


class AgentResponse(BaseModel):
    """Response from the agent."""

    message: str
    actions_taken: list[str] = []
    suggestions: list[str] = []


def create_agent(
    model: str = "anthropic:claude-3-5-sonnet-latest",
) -> Agent[AgentDependencies, AgentResponse]:
    """
    Create the main Merlya agent.

    Args:
        model: Model to use (PydanticAI format).

    Returns:
        Configured Agent instance.
    """
    agent = Agent(
        model,
        deps_type=AgentDependencies,
        output_type=AgentResponse,
        system_prompt=SYSTEM_PROMPT,
        defer_model_check=True,  # Allow dynamic model names
    )

    register_all_tools(agent)

    return agent


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
        self.model = model
        self._agent = create_agent(model)
        self._history: list[dict[str, str]] = []
        self._active_conversation: Conversation | None = None

    async def run(
        self,
        user_input: str,
        router_result: RouterResult | None = None,
    ) -> AgentResponse:
        """
        Process user input.

        Args:
            user_input: User message.
            router_result: Optional routing result.

        Returns:
            Agent response.
        """
        try:
            # Create conversation lazily on first user message
            if self._active_conversation is None:
                self._active_conversation = await self._create_conversation(user_input)

            # Append user message to history before invoking the LLM
            self._history.append({"role": "user", "content": user_input})

            deps = AgentDependencies(
                context=self.context,
                router_result=router_result,
            )

            augmented_input = user_input
            if router_result and (router_result.credentials_required or router_result.elevation_required):
                flag_note = (
                    f"[router_flags credentials_required={router_result.credentials_required} "
                    f"elevation_required={router_result.elevation_required}]"
                )
                    # Without interfering with user text, prepend a short note
                augmented_input = f"{flag_note}\n{user_input}"

            result = await self._agent.run(
                augmented_input,
                deps=deps,
                message_history=self._history,  # type: ignore[arg-type]
            )

            # Update history
            self._history.append({"role": "assistant", "content": result.output.message})

            await self._persist_history()

            return result.output

        except Exception as e:
            logger.error(f"Agent error: {e}")
            # Add error response to history to maintain conversation consistency
            error_message = f"An error occurred: {e}"
            self._history.append({"role": "assistant", "content": error_message})
            # Persist the complete conversation history including error
            await self._persist_history()
            return AgentResponse(
                message=error_message,
                actions_taken=[],
                suggestions=["Try rephrasing your request"],
            )

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._history.clear()
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
            logger.debug(f"Failed to persist conversation start: {e}")
        return conv

    async def _persist_history(self) -> None:
        """Persist current history into the active conversation."""
        if not self._active_conversation:
            return

        self._active_conversation.messages = [msg.copy() for msg in self._history]
        if not self._active_conversation.title:
            self._active_conversation.title = self._derive_title(
                next((m["content"] for m in self._history if m.get("role") == "user"), "")
            )

        try:
            await self.context.conversations.update(self._active_conversation)
        except Exception as e:
            logger.debug(f"Failed to persist conversation history: {e}")

    def load_conversation(self, conv: Conversation) -> None:
        """Load an existing conversation into the agent history."""
        self._active_conversation = conv
        self._history = list(conv.messages or [])
        logger.debug(f"Loaded conversation {conv.id[:8]}")

    def _derive_title(self, seed: str | None) -> str:
        """Generate a short title from the first user message."""
        if not seed:
            return "Conversation"
        text = seed.strip().splitlines()[0]
        return (text[:60] + "...") if len(text) > 60 else text
