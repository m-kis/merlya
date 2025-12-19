"""
Merlya Router - Intent classification (DEPRECATED).

The router is no longer used for routing in the new architecture.
All routing is now handled by:
  - "/" commands → Slash command dispatch (fast-path)
  - Free text → Orchestrator (LLM delegates to specialists)

This module is kept for backward compatibility and may be removed
in a future version.
"""

# Backward compatibility imports - these may be used by tests and legacy code
from merlya.router.classifier import (
    FAST_PATH_INTENTS,
    FAST_PATH_PATTERNS,
    AgentMode,
    IntentClassifier,
    IntentRouter,
    RouterResult,
)
from merlya.router.handler import (
    HandlerResponse,
    handle_agent,
    handle_fast_path,
    handle_skill_flow,
    handle_user_message,
)

__all__ = [
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    "AgentMode",
    "HandlerResponse",
    "IntentClassifier",
    "IntentRouter",
    "RouterResult",
    "handle_agent",
    "handle_fast_path",
    "handle_skill_flow",
    "handle_user_message",
]
