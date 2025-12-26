"""
Merlya Router - Intent classification.

Provides intent classification and routing:
  - CenterClassifier: Routes between DIAGNOSTIC/CHANGE centers
  - IntentRouter: Legacy router for backward compatibility
  - "/" commands: Slash command dispatch (fast-path)
"""

# New architecture: Center classifier
from merlya.router.center_classifier import (
    CenterClassification,
    CenterClassifier,
)

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
    # New architecture
    "CenterClassification",
    "CenterClassifier",
    # Legacy
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
