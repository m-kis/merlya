"""
Merlya Router - Intent classification.

Classifies user input to determine agent mode and tools.
"""

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
    # Fast path
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    # Classifier
    "AgentMode",
    # Handler
    "HandlerResponse",
    "IntentClassifier",
    "IntentRouter",
    "RouterResult",
    "handle_agent",
    "handle_fast_path",
    "handle_skill_flow",
    "handle_user_message",
]
