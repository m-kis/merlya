"""
Orchestrator package.

Re-exports all public symbols for backward compatibility.
"""

from __future__ import annotations

from .center_integration import convert_center_result as _convert_center_result
from .constants import INJECTION_PATTERNS, MAX_SPECIALIST_RETRIES, SPECIALIST_LIMITS
from .core import Orchestrator, create_orchestrator
from .models import (
    DelegationResult,
    OrchestratorDeps,
    OrchestratorResponse,
    SecurityError,
)
from .prompts import ORCHESTRATOR_PROMPT
from .sanitization import sanitize_user_input

__all__ = [
    "INJECTION_PATTERNS",
    "MAX_SPECIALIST_RETRIES",
    "ORCHESTRATOR_PROMPT",
    "SPECIALIST_LIMITS",
    "DelegationResult",
    "Orchestrator",
    "OrchestratorDeps",
    "OrchestratorResponse",
    "SecurityError",
    "_convert_center_result",
    "create_orchestrator",
    "sanitize_user_input",
]
