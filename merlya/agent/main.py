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
from pydantic_ai import Agent, ModelMessage, ModelMessagesTypeAdapter, ModelRetry, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from merlya.agent.history import create_loop_aware_history_processor, detect_loop
from merlya.agent.tools import register_all_tools
from merlya.config.constants import (
    DEFAULT_REQUEST_LIMIT,
    DEFAULT_TOOL_CALLS_LIMIT,
    DEFAULT_TOOL_RETRIES,
    MIN_RESPONSE_LENGTH_WITH_ACTIONS,
    TITLE_MAX_LENGTH,
)
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
1. BE DIRECT: Try the most obvious path FIRST. If user says "it's probably in /root", directly read /root/. Don't explore randomly.
2. TRUST USER HINTS: When user provides location hints, use them immediately. Don't verify with ls before cat.
3. ONE COMMAND IS BETTER: Prefer one direct command over many exploratory commands.
4. Ask for confirmation only before destructive actions (delete, stop, restart).
5. Use sudo directly when user mentions privilege elevation (e.g., "avec sudo", "as root").
6. If the router signals `credentials_required` or `elevation_required`, use the proper tool.

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

## Secrets in Commands

When the user provides a secret reference like `@secret-name`, use it directly in commands.
Merlya will automatically resolve the secret at execution time.

Example:
- User says: "Connect to MongoDB with password @db-password"
- You execute: `ssh_execute(command="mongosh -u admin -p @db-password")`
- Merlya resolves `@db-password` from keyring before execution
- Logs will show `@db-password`, never the actual value

IMPORTANT: Never ask the user to type passwords in the chat. Always use `@secret-name` references.

## Privilege Elevation (Automatic)

Merlya handles privilege elevation automatically:
- If a command fails with "Permission denied", Merlya will retry with elevation
- The user will be prompted to confirm elevation (su/sudo/doas)
- You don't need to prefix commands with `sudo` - Merlya detects and handles it

Just execute commands normally. If elevation is needed, Merlya handles it:
```
# Simply execute the command
result = ssh_execute(host="db-server", command="cat /var/log/mongodb/mongod.log")
# If permission denied, Merlya auto-retries with elevation after user confirmation
```

## SECURITY: Password Handling (CRITICAL)

NEVER construct commands with passwords in clear text! This is a CRITICAL security rule.

FORBIDDEN patterns (NEVER DO THIS):
- `echo 'password' | sudo -S ...`  <- LEAKS PASSWORD IN LOGS!
- `mysql -p'password' ...`  <- LEAKS PASSWORD!
- Any command with a literal password embedded

CORRECT approach:
1. Use `request_credentials` to get credentials - it returns safe references like `@sudo:host:password`
2. Use these references in commands: `ssh_execute(command="mysql -p @db:host:password")`
3. Merlya resolves references at execution time - logs show `@secret-name`, never actual values

If you need sudo with a password, just use `sudo command` - Merlya will:
1. Detect the permission error
2. Ask the user for the password
3. Store it securely and retry with the password via stdin (not echoed)

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

## Task Focus (CRITICAL)

Stay focused on the user's specific request. Do NOT:
- Explore directories randomly without purpose
- Run `ls -la` on multiple unrelated paths
- Gather information that isn't directly relevant to the current task
- Drift into general system exploration when asked about a specific topic

DO:
- Identify the specific goal from the user's message
- Take direct, purposeful actions toward that goal
- If you need to explore, explain WHY before each action
- If you get stuck, ASK the user for clarification instead of exploring randomly

When the user says "continue":
- Review what was already accomplished in the conversation
- Identify the next logical step toward the original goal
- Do NOT start over or explore from scratch

Example of BAD behavior:
User: "Check MongoDB logs for errors"
Agent: *runs ls -la on /var, /etc, /home, /opt, /tmp...*  <- WRONG!

Example of GOOD behavior:
User: "Check MongoDB logs for errors"
Agent: "I'll check the MongoDB logs. Let me read the log file."
*reads /var/log/mongodb/mongod.log or equivalent*  <- CORRECT!

Example of DIRECT behavior (BEST):
User: "Check cloudflared config on @server, I think it's in root's home, use sudo"
Agent: *ssh_execute(host="server", command="sudo cat /root/.cloudflared/config.yml")* <- ONE COMMAND, DONE!

NOT: ls -la /root, find / -name "*.yml", ps aux | grep cloudflared, etc. <- TOO MANY COMMANDS!
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
    max_history_messages: int = 30,
) -> Agent[AgentDependencies, AgentResponse]:
    """
    Create the main Merlya agent.

    Args:
        model: Model to use (PydanticAI format).
        max_history_messages: Maximum messages to keep in history.

    Returns:
        Configured Agent instance.
    """
    history_processor = create_loop_aware_history_processor(max_messages=max_history_messages)

    agent = Agent(
        model,
        deps_type=AgentDependencies,
        output_type=AgentResponse,
        system_prompt=SYSTEM_PROMPT,
        defer_model_check=True,  # Allow dynamic model names
        history_processors=[history_processor],
        retries=DEFAULT_TOOL_RETRIES,  # Allow tool retries for elevation/credential flows
    )

    register_all_tools(agent)

    @agent.system_prompt
    def inject_router_context(ctx: RunContext[AgentDependencies]) -> str:
        """
        Inject router context as dynamic system prompt.

        Adds contextual information from the intent router to guide
        the agent's behavior. Includes:
        - Credential/elevation requirements from router flags
        - Jump host information for SSH tunneling
        - Detected operation mode (diagnostic, remediation, etc.)

        Args:
            ctx: Run context with agent dependencies.

        Returns:
            Dynamic system prompt string, empty if no router context.
        """
        router_result = ctx.deps.router_result
        if not router_result:
            return ""

        parts = []

        # Add credentials/elevation context
        if router_result.credentials_required or router_result.elevation_required:
            parts.append(
                f"⚠️ ROUTER CONTEXT: credentials_required={router_result.credentials_required}, "
                f"elevation_required={router_result.elevation_required}. "
                "Address these requirements using the appropriate tools before proceeding."
            )

        # Add jump host context
        if router_result.jump_host:
            parts.append(
                f"🔗 JUMP HOST DETECTED: {router_result.jump_host}. "
                f'For SSH commands, use via="{router_result.jump_host}" parameter in ssh_execute.'
            )

        # Add detected mode context
        if router_result.mode:
            parts.append(f"📋 Detected mode: {router_result.mode.value}")

        return "\n".join(parts) if parts else ""

    @agent.output_validator
    def validate_response(
        _ctx: RunContext[AgentDependencies],
        output: AgentResponse,
    ) -> AgentResponse:
        """Validate the agent response for coherence."""
        # Check for empty message
        if not output.message or not output.message.strip():
            raise ModelRetry("Response message cannot be empty. Please provide a meaningful response.")

        # Check for overly short responses when actions were taken
        if output.actions_taken and len(output.message) < MIN_RESPONSE_LENGTH_WITH_ACTIONS:
            raise ModelRetry(
                "Response is too brief given the actions taken. "
                "Please explain what was done and the results."
            )

        # Warn in logs if message indicates an error but no suggestions provided
        # Use word boundaries to avoid false positives (e.g., "impossible" in "not impossible")
        import re

        error_pattern = r"\b(error|failed|cannot|unable|impossible)\b"
        has_error = re.search(error_pattern, output.message, re.IGNORECASE) is not None
        if has_error and not output.suggestions:
            logger.debug("⚠️ Response indicates an error but no suggestions provided")

        return output

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
            UsageLimits are high failsafes - not workflow controls.
        """
        # Apply usage limits: use router's dynamic limits if available
        # These are HIGH limits - just failsafes, not workflow controls
        # Loop detection (history.py) handles the real safety
        if usage_limits is None:
            if router_result is not None:
                request_limit = router_result.request_limit
                tool_limit = router_result.tool_calls_limit
            else:
                request_limit = DEFAULT_REQUEST_LIMIT
                tool_limit = DEFAULT_TOOL_CALLS_LIMIT

            usage_limits = UsageLimits(
                request_limit=request_limit,
                tool_calls_limit=tool_limit,
            )
        try:
            # Create conversation lazily on first user message
            if self._active_conversation is None:
                self._active_conversation = await self._create_conversation(user_input)

            deps = AgentDependencies(
                context=self.context,
                router_result=router_result,
            )

            # Run the agent - it completes naturally via ReAct loop
            # Loop detection in history processor catches unproductive behavior
            try:
                result = await self._agent.run(
                    user_input,
                    deps=deps,
                    message_history=self._message_history if self._message_history else None,
                    usage_limits=usage_limits,
                )
            except UsageLimitExceeded as e:
                # This should rarely happen with high limits
                # If it does, the task is genuinely too complex
                logger.warning(f"⚠️ Failsafe limit reached: {e}")
                await self._persist_history()
                return AgentResponse(
                    message=f"Tâche trop complexe - limite de sécurité atteinte: {e}",
                    actions_taken=[],
                    suggestions=["Découper la tâche en étapes plus petites"],
                )

            # Update history with ALL messages including tool calls
            # This is critical for conversation continuity
            self._message_history = result.all_messages()

            # Check for persistent loop AFTER the run
            # The history processor injects a warning, but if the LLM ignores it,
            # we catch it here and return a structured response to the user
            is_loop, loop_desc = detect_loop(
                self._message_history,
                threshold_same=4,  # Strict: 4 identical calls = hard stop
                threshold_pattern=5,
            )
            if is_loop and loop_desc:
                logger.warning(f"🔄 Persistent loop detected: {loop_desc}")
                await self._persist_history()
                return AgentResponse(
                    message=(
                        f"Je suis bloqué dans une boucle : {loop_desc}. "
                        "Je n'arrive pas à progresser avec cette approche."
                    ),
                    actions_taken=[],
                    suggestions=[
                        "Vérifier les prérequis (service installé, permissions)",
                        "Essayer une commande différente",
                        "Fournir plus de contexte sur l'environnement",
                    ],
                )

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
