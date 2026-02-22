"""
Merlya Agent - Factory for creating the main agent.

Creates and configures the PydanticAI agent with specialist delegation tools.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.history import create_history_processor
from merlya.agent.orchestrator.specialist_tools import register_specialist_tools
from merlya.agent.prompts import MAIN_AGENT_PROMPT
from merlya.agent.tools.core import credentials, hosts, user_interaction
from merlya.agent.tools_mcp import register_mcp_tools
from merlya.config.constants import MIN_RESPONSE_LENGTH_WITH_ACTIONS

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies, AgentResponse

# Number of tool retries: 3 is enough for elevation/credential retry flows
_TOOL_RETRIES = 3


def create_agent(
    model: str = "anthropic:claude-3-5-sonnet-latest",
    max_history_messages: int = 30,
) -> Agent[AgentDependencies, AgentResponse]:
    """
    Create the main Merlya agent.

    The agent orchestrates by delegating to specialists:
    - delegate_diagnostic  → read-only investigation
    - delegate_execution   → mutations with HITL confirmation
    - delegate_security    → security audits
    - delegate_query       → inventory queries

    Args:
        model: Model to use (PydanticAI format).
        max_history_messages: Maximum messages to keep in history.

    Returns:
        Configured Agent instance.
    """
    from merlya.agent.main import AgentDependencies, AgentResponse

    history_processor = create_history_processor(max_messages=max_history_messages)

    agent: Agent[AgentDependencies, AgentResponse] = Agent(
        model,
        deps_type=AgentDependencies,
        output_type=AgentResponse,
        system_prompt=MAIN_AGENT_PROMPT,
        defer_model_check=True,
        history_processors=[history_processor],
        retries=_TOOL_RETRIES,
    )

    # Register specialist delegation tools (DIAG / CHANGE guardrails)
    register_specialist_tools(agent)

    # Register direct utility tools (inventory + interaction only)
    hosts.register(agent)
    user_interaction.register(agent)
    credentials.register(agent)

    # Register MCP tools if configured
    register_mcp_tools(agent)

    _register_response_validator(agent)

    return agent


def _register_response_validator(agent: Agent[AgentDependencies, AgentResponse]) -> None:
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
