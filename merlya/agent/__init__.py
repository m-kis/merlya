"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent that delegates to specialists (DIAG/CHANGE guardrails).
"""

from merlya.agent.agent_factory import create_agent
from merlya.agent.confirmation import (
    ConfirmationResult,
    ConfirmationState,
    DangerLevel,
    confirm_command,
    detect_danger_level,
)
from merlya.agent.history import (
    create_history_processor,
    limit_history,
    validate_tool_pairing,
)
from merlya.agent.main import (
    AgentDependencies,
    AgentResponse,
    MerlyaAgent,
)
from merlya.agent.specialists import (
    run_diagnostic_agent,
    run_execution_agent,
    run_query_agent,
    run_security_agent,
)
from merlya.agent.tracker import ToolCallTracker

__all__ = [
    "AgentDependencies",
    "AgentResponse",
    "ConfirmationResult",
    "ConfirmationState",
    "DangerLevel",
    "MerlyaAgent",
    "ToolCallTracker",
    "confirm_command",
    "create_agent",
    "create_history_processor",
    "detect_danger_level",
    "limit_history",
    "run_diagnostic_agent",
    "run_execution_agent",
    "run_query_agent",
    "run_security_agent",
    "validate_tool_pairing",
]
