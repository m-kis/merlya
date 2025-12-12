"""
Merlya Agent - Main agent implementation.

PydanticAI-based agent with ReAct loop.
"""

from merlya.agent.history import (
    create_history_processor,
    create_loop_aware_history_processor,
    detect_loop,
    limit_history,
    validate_tool_pairing,
)
from merlya.agent.main import (
    AgentDependencies,
    AgentResponse,
    MerlyaAgent,
    create_agent,
)

__all__ = [
    "AgentDependencies",
    "AgentResponse",
    "MerlyaAgent",
    "create_agent",
    "create_history_processor",
    "create_loop_aware_history_processor",
    "detect_loop",
    "limit_history",
    "validate_tool_pairing",
]
