"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent with ReAct loop and Orchestrator pattern.
"""

from merlya.agent.confirmation import (
    ConfirmationResult,
    ConfirmationState,
    DangerLevel,
    confirm_command,
    detect_danger_level,
)
from merlya.agent.history import (
    create_history_processor,
    create_loop_aware_history_processor,
    limit_history,
    validate_tool_pairing,
)
from merlya.agent.main import (
    AgentDependencies,
    AgentResponse,
    MerlyaAgent,
    create_agent,
)
from merlya.agent.orchestrator import (
    Orchestrator,
    OrchestratorDeps,
    OrchestratorResponse,
    create_orchestrator,
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
    "Orchestrator",
    "OrchestratorDeps",
    "OrchestratorResponse",
    "ToolCallTracker",
    "confirm_command",
    "create_agent",
    "create_history_processor",
    "create_loop_aware_history_processor",
    "create_orchestrator",
    "detect_danger_level",
    "limit_history",
    "run_diagnostic_agent",
    "run_execution_agent",
    "run_query_agent",
    "run_security_agent",
    "validate_tool_pairing",
]
