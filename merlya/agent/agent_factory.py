"""
Merlya Agent - Factory for creating the main agent.

Creates and configures the PydanticAI agent with all tools and validators.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.history import create_loop_aware_history_processor
from merlya.agent.prompts import MAIN_AGENT_PROMPT
from merlya.agent.tools import register_all_tools
from merlya.config.constants import DEFAULT_TOOL_RETRIES, MIN_RESPONSE_LENGTH_WITH_ACTIONS

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies, AgentResponse


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
    # Import here to avoid circular imports
    from merlya.agent.main import AgentDependencies, AgentResponse

    history_processor = create_loop_aware_history_processor(max_messages=max_history_messages)

    agent: Agent[AgentDependencies, AgentResponse] = Agent(
        model,
        deps_type=AgentDependencies,
        output_type=AgentResponse,
        system_prompt=MAIN_AGENT_PROMPT,
        defer_model_check=True,  # Allow dynamic model names
        history_processors=[history_processor],
        retries=DEFAULT_TOOL_RETRIES,  # Allow tool retries for elevation/credential flows
    )

    register_all_tools(agent)
    _register_router_context_prompt(agent)
    _register_response_validator(agent)

    return agent


def _register_router_context_prompt(agent: Agent[Any, Any]) -> None:
    """Register the router context system prompt."""

    @agent.system_prompt
    def inject_router_context(ctx: RunContext[AgentDependencies]) -> str:
        """Inject router context as dynamic system prompt."""
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

        # Add extracted target hosts (CRITICAL: tells the LLM which hosts to operate on)
        target_hosts = router_result.entities.get("hosts", [])
        if target_hosts:
            hosts_list = ", ".join(target_hosts)
            logger.info(f"🎯 Injecting TARGET HOSTS context: {hosts_list}")
            parts.append(
                f"🎯 TARGET HOSTS: {hosts_list}. "
                f"CRITICAL: Call ssh_execute(host_name='{target_hosts[0]}', command='...') directly. "
                f"The host '{target_hosts[0]}' exists in inventory - DO NOT use list_hosts or ask_user. "
                "DO NOT run bash commands locally. Always use ssh_execute for remote hosts."
            )

        # Add unresolved hosts context (proactive mode)
        if router_result.unresolved_hosts:
            hosts_list = ", ".join(router_result.unresolved_hosts)
            parts.append(
                f"🔍 PROACTIVE: Hosts not in inventory: {hosts_list}. "
                "These may be valid hostnames - try direct connection. "
                "If connection fails, use bash/ssh_execute to discover alternatives."
            )

        return "\n".join(parts) if parts else ""


def _register_response_validator(agent: Agent[Any, Any]) -> None:
    """Register the response validator."""

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
        error_pattern = r"\b(error|failed|cannot|unable|impossible)\b"
        has_error = re.search(error_pattern, output.message, re.IGNORECASE) is not None
        if has_error and not output.suggestions:
            logger.debug("⚠️ Response indicates an error but no suggestions provided")

        return output
