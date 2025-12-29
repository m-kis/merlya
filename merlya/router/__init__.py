"""
Merlya Router - Intent classification.

Provides intent classification and routing:
  - SmartExtractor: Fast LLM-based entity extraction and intent classification (v0.8.0)
  - CenterClassifier: Routes between DIAGNOSTIC/CHANGE centers
  - IntentRouter: Main router with SmartExtractor integration
  - "/" commands: Slash command dispatch (fast-path)
"""

# New architecture: SmartExtractor (fast LLM)
# Center classifier
from merlya.router.center_classifier import (
    CenterClassification,
    CenterClassifier,
)

# Main router with SmartExtractor integration
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
from merlya.router.smart_extractor import (
    ExtractedEntities,
    IntentClassification,
    SmartExtractionResult,
    SmartExtractor,
    get_smart_extractor,
)

__all__ = [
    # Main router
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    "AgentMode",
    # Center classifier
    "CenterClassification",
    "CenterClassifier",
    # New architecture (v0.8.0)
    "ExtractedEntities",
    "HandlerResponse",
    "IntentClassification",
    "IntentClassifier",
    "IntentRouter",
    "RouterResult",
    "SmartExtractionResult",
    "SmartExtractor",
    "get_smart_extractor",
    "handle_agent",
    "handle_fast_path",
    "handle_skill_flow",
    "handle_user_message",
]
