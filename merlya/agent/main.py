"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent with ReAct loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel
from pydantic_ai import Agent, ModelMessage, ModelMessagesTypeAdapter

from merlya.agent.tools import register_all_tools
from merlya.config.constants import TITLE_MAX_LENGTH
from merlya.config.provider_env import ensure_provider_env

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

## Jump Hosts / Bastions

When the user asks to access a remote host "via" or "through" another host (bastion/jump host),
use the `via` parameter of `ssh_execute` to tunnel the connection.

Examples of user requests that require the `via` parameter:
- "Check disk usage on db-server via bastion"
- "Analyse this machine 51.68.25.89 via @ansible"
- "Execute 'uptime' on web-01 through the jump host"

For these requests, use: ssh_execute(host="target_host", command="...", via="bastion_host")

The `via` parameter:
- Can be a host name from inventory (e.g., "ansible", "bastion") or an IP/hostname
- Creates an SSH tunnel through the jump host to reach the target
- Takes priority over any jump_host configured in the host's inventory entry

IMPORTANT: When the user says "via @hostname" or "through @hostname", ALWAYS use the via parameter.
Do NOT try to connect directly to hosts that require a jump host - this will timeout.

## Coherence Verification (CRITICAL)

Before providing ANY analysis, you MUST verify the coherence of your findings.
This applies to ALL types of data: numerical, temporal, status, counts, etc.

### Core principle: CROSS-CHECK EVERYTHING

Before concluding, ask yourself:
1. "Do the numbers add up?"
2. "Does my conclusion match ALL the evidence?"
3. "Have I accounted for the full picture?"

### Mandatory verification patterns:

1. **Quantitative coherence** (numbers, sizes, counts, durations):
   - Sum of parts ≈ total (within reasonable margin)
   - If you find a gap > 10%, investigate before concluding
   - Don't claim "X is the cause" if X only explains a fraction of the observed effect

2. **Logical coherence** (cause-effect, status, states):
   - Symptoms must match the diagnosis
   - If service is "running" but "not responding", investigate the contradiction
   - Root cause must explain ALL observed symptoms, not just some

3. **Temporal coherence** (times, sequences, logs):
   - Events must follow logical order
   - If issue started at T1, the cause must precede T1
   - Correlate timestamps across different sources

4. **Completeness check**:
   - "Have I explored all relevant locations/sources?"
   - "Could there be data I'm missing?" (hidden files, other partitions, filtered logs)
   - If analysis is partial, explicitly state what's missing

### Red flags to catch:

- Claiming "biggest/main cause" without verifying it explains the majority
- Drawing conclusions from a single data point
- Ignoring contradictory evidence
- Assuming completeness without verification

### When findings are incomplete:

⚠️ Always state: "Current analysis accounts for X of Y" or "Analysis based on partial data"
- Suggest additional commands/checks to fill gaps
- Do NOT present partial findings as complete conclusions

### Self-check before responding:

"Does my conclusion logically follow from ALL the data I collected?"
"Would my analysis survive scrutiny if someone checked my math/logic?"
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
        ensure_provider_env(self.context.config)
        self.model = model
        self._agent = create_agent(model)
        self._message_history: list[ModelMessage] = []
        self._active_conversation: Conversation | None = None

    async def run(
        self,
        user_input: str,
        router_result: RouterResult | None = None,
        timeout: float = 120.0,
    ) -> AgentResponse:
        """
        Process user input.

        Args:
            user_input: User message.
            router_result: Optional routing result.
            timeout: Maximum time to wait for LLM response (default 120s).

        Returns:
            Agent response.
        """
        try:
            # Create conversation lazily on first user message
            if self._active_conversation is None:
                self._active_conversation = await self._create_conversation(user_input)

            deps = AgentDependencies(
                context=self.context,
                router_result=router_result,
            )

            augmented_input = user_input
            if router_result:
                notes = []
                if router_result.credentials_required or router_result.elevation_required:
                    notes.append(
                        f"credentials_required={router_result.credentials_required} "
                        f"elevation_required={router_result.elevation_required}"
                    )
                if router_result.jump_host:
                    # Explicit instruction for the LLM to use jump host
                    notes.append(
                        f"JUMP_HOST_DETECTED={router_result.jump_host} "
                        f'(USE via="{router_result.jump_host}" in ssh_execute calls)'
                    )
                if notes:
                    flag_note = f"[router_flags {' '.join(notes)}]"
                    augmented_input = f"{flag_note}\n{user_input}"

            # Pass message_history only if we have previous messages
            # This includes tool calls, tool results, and assistant responses
            # Wrap with timeout to prevent infinite hangs on LLM provider issues
            try:
                result = await asyncio.wait_for(
                    self._agent.run(
                        augmented_input,
                        deps=deps,
                        message_history=self._message_history if self._message_history else None,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning(f"⏱️ LLM request timed out after {timeout}s")
                await self._persist_history()
                return AgentResponse(
                    message=f"Request timed out after {timeout}s. The LLM provider may be slow or unresponsive.",
                    actions_taken=[],
                    suggestions=["Try again", "Check your internet connection"],
                )

            # Update history with ALL messages including tool calls
            # This is critical for conversation continuity
            self._message_history = result.all_messages()

            await self._persist_history()

            return result.output

        except asyncio.CancelledError:
            # Task was cancelled (e.g., by Ctrl+C)
            logger.debug("Agent task cancelled")
            await self._persist_history()
            raise

        except Exception as e:
            logger.error(f"Agent error: {e}")
            # Don't modify history on error - keep the valid state
            await self._persist_history()
            return AgentResponse(
                message=f"An error occurred: {e}",
                actions_taken=[],
                suggestions=["Try rephrasing your request"],
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
            logger.debug(f"Failed to persist conversation start: {e}")
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
            logger.debug(f"Failed to persist conversation history: {e}")

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
