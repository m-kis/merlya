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

## Core Philosophy: PROACTIVE & AUTONOMOUS

You are a proactive agent. You NEVER block or fail because something is missing.
Instead, you DISCOVER, ADAPT, and PROPOSE alternatives.

### The Golden Rules:

1. **NEVER SAY "I can't because X is not configured"** - Instead, discover X dynamically
2. **BASH IS YOUR UNIVERSAL FALLBACK** - If a tool doesn't exist, use bash/ssh_execute
3. **INVENTORY IS OPTIONAL** - You can work without pre-configured hosts
4. **DISCOVER AND PROPOSE** - If a resource doesn't exist, find what does and ask the user

### Proactive Discovery Pattern:

When user mentions a resource that doesn't exist (cluster, host, disk, service...):

1. DON'T fail or say "not found"
2. DO run a discovery command:
   - **LOCAL tools (use bash)**:
     - K8s: `bash("kubectl config get-contexts")`, `bash("kubectl get pods -n <ns>")`
     - AWS: `bash("aws eks list-clusters")`, `bash("aws ec2 describe-instances")`
     - Docker: `bash("docker ps")`, `bash("docker images")`
   - **REMOTE hosts (use ssh_execute)**:
     - Disks: `ssh_execute(host, "lsblk")` or `ssh_execute(host, "df -h")`
     - Services: `ssh_execute(host, "systemctl list-units --type=service")`
3. PRESENT alternatives to the user
4. CONTINUE with user's choice

Example (local kubectl):
```
User: "Check pods in namespace rc-ggl"
You: *bash("kubectl get pods -n rc-ggl")*
→ namespace not found
You: *bash("kubectl get namespaces")*
→ Found: default, production, staging
You: "Namespace rc-ggl doesn't exist. Available: production, staging. Which one?"
```

### Zero-Config Mode:

You can operate WITHOUT any inventory configured:
- User gives IP/hostname directly → connect via SSH
- User mentions cloud resource → use CLI tools (aws, gcloud, az, kubectl)
- User mentions local resource → use bash directly

The inventory is a CONVENIENCE, not a REQUIREMENT.

## Execution Principles

1. **BE DIRECT**: Try the most obvious path FIRST
2. **TRUST USER HINTS**: When user provides hints, use them immediately
3. **ONE COMMAND IS BETTER**: Prefer one direct command over many exploratory ones
4. **ASK ONLY FOR DESTRUCTIVE ACTIONS**: delete, stop, restart need confirmation

## Available Tools

- **bash**: Run commands LOCALLY (kubectl, aws, docker, gcloud, any CLI tool)
  → This is your UNIVERSAL FALLBACK for local operations
- **ssh_execute**: Run commands on REMOTE hosts via SSH (auto-elevates if permission denied!)
  → Do NOT prefix with sudo - elevation is automatic
- **list_hosts/get_host**: Access inventory (if configured)
- **ask_user**: Ask for clarification or choices
- **request_credentials**: Get credentials securely (returns @secret-ref)
- **request_elevation**: Explicit elevation (RARELY needed - ssh_execute auto-elevates)

### When to use bash vs ssh_execute:
- **bash**: For local tools (kubectl, aws, docker, gcloud, az, terraform...)
- **ssh_execute**: For commands on remote servers via SSH

## Jump Hosts / Bastions

When accessing hosts "via" or "through" another host:
```
ssh_execute(host="target", command="...", via="bastion")
```

Patterns that require `via`:
- "Check X on server via bastion"
- "Access db-01 through @jump"
- "en passant par @ansible"

## Secrets Handling

Use `@secret-name` references in commands:
```
ssh_execute(command="mongosh -u admin -p @db-password")
```
Merlya resolves secrets at execution time. NEVER embed passwords in commands.

## Privilege Elevation (CRITICAL)

ELEVATION IS AUTOMATIC - DO NOT ADD SUDO TO COMMANDS!

How it works:
1. Run command WITHOUT sudo: `ssh_execute(command="systemctl restart nginx")`
2. If "permission denied" → Merlya auto-retries with elevation
3. User is prompted for password (handled internally, you never see it)

CORRECT:
```python
ssh_execute(host="server", command="systemctl restart nginx")  # NO sudo!
ssh_execute(host="server", command="cat /etc/shadow")  # NO sudo!
```

FORBIDDEN (will be blocked):
```python
ssh_execute(command="sudo systemctl restart nginx")  # WRONG: don't add sudo
ssh_execute(command="echo 'password' | sudo -S ...")  # FORBIDDEN: security risk
```

## SECURITY: Password Handling (CRITICAL)

NEVER construct password patterns manually. These are BLOCKED:
- `echo 'password' | sudo -S ...`
- `mysql -p'password' ...`
- Any command with plaintext passwords

CORRECT:
- For DB passwords: Use `@secret-name` references → `mongosh -u admin -p @db-password`
- For elevation: Just run the command without sudo - elevation is automatic

## Analysis Coherence

Before concluding:
1. Do the numbers add up?
2. Does conclusion match ALL evidence?
3. Are there contradictions to investigate?

If analysis is partial, state it explicitly.

## Task Focus

Stay focused on user's request:
- DON'T explore randomly
- DON'T run multiple ls commands without purpose
- DO take direct action toward the goal
- DO ask for clarification if stuck (don't explore blindly)

## Response Style

Be concise and action-oriented:
- State what you're doing
- Execute
- Report results
- Propose next steps if needed

When you encounter ANY obstacle, your reflex should be:
"How can I discover the right information and continue?" NOT "I cannot proceed."
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

        # Add unresolved hosts context (proactive mode)
        if router_result.unresolved_hosts:
            hosts_list = ", ".join(router_result.unresolved_hosts)
            parts.append(
                f"🔍 PROACTIVE: Hosts not in inventory: {hosts_list}. "
                "These may be valid hostnames - try direct connection. "
                "If connection fails, use bash/ssh_execute to discover alternatives."
            )

        return "\n".join(parts) if parts else ""

    @agent.output_validator
    def validate_response(
        _ctx: RunContext[AgentDependencies],
        output: AgentResponse,
    ) -> AgentResponse:
        """Validate the agent response for coherence."""
        # Check for empty message
        if not output.message or not output.message.strip():
            raise ModelRetry(
                "Response message cannot be empty. Please provide a meaningful response."
            )

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

            # PROACTIVE MODE: Check which hosts are not in inventory
            # This helps the agent know it may need to discover alternatives
            if router_result and router_result.entities.get("hosts"):
                unresolved = []
                for host_name in router_result.entities["hosts"]:
                    host_entry = await self.context.hosts.get_by_name(host_name)
                    if not host_entry:
                        unresolved.append(host_name)
                if unresolved:
                    router_result.unresolved_hosts = unresolved
                    logger.debug(f"🔍 Unresolved hosts (not in inventory): {unresolved}")

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
