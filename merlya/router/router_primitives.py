"""
Merlya Router - Shared primitives for intent routing.

This module contains the lightweight constants and parsing helpers used by
`merlya.router.classifier.IntentRouter`. It exists to keep `classifier.py`
below the ~600 LOC guideline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from merlya.config.constants import (
    DEFAULT_REQUEST_LIMIT,
    DEFAULT_TOOL_CALLS_LIMIT,
    REQUEST_LIMIT_CHAT,
    REQUEST_LIMIT_DIAGNOSTIC,
    REQUEST_LIMIT_QUERY,
    REQUEST_LIMIT_REMEDIATION,
    TOOL_CALLS_LIMIT_CHAT,
    TOOL_CALLS_LIMIT_DIAGNOSTIC,
    TOOL_CALLS_LIMIT_QUERY,
    TOOL_CALLS_LIMIT_REMEDIATION,
)
from merlya.router.intent_classifier import AgentMode


class _LLMClassification(BaseModel):
    """Structured LLM output for intent classification (PydanticAI output_type)."""

    mode: Literal["diagnostic", "remediation", "query", "chat"] = "chat"
    tools: list[str] = Field(default_factory=lambda: ["core"])
    credentials_required: bool = False
    elevation_required: bool = False
    reasoning: str | None = None


class _LLMSkillMatch(BaseModel):
    """Structured LLM output for skill matching (PydanticAI output_type)."""

    skill: str | None = None
    confidence: float = 0.0
    reason: str | None = None


# Fast path intents - operations that can be handled without LLM
# These are simple database queries or direct operations
FAST_PATH_INTENTS = frozenset(
    {
        "host.list",  # List hosts from inventory
        "host.details",  # Get details for a specific host
        "group.list",  # List host groups/tags
        "skill.list",  # List available skills
        "var.list",  # List variables
        "var.get",  # Get a specific variable
    }
)

# Patterns to detect fast path intents
FAST_PATH_PATTERNS: dict[str, list[str]] = {
    "host.list": [
        r"^(?:liste?|show|display|voir)\s+(?:les?\s+)?(?:hosts?|machines?|serveurs?)",
        r"^(?:quels?\s+sont\s+)?(?:mes?\s+)?(?:hosts?|machines?|serveurs?)",
        r"^(?:inventory|inventaire)",
    ],
    "host.details": [
        # Require explicit @ to avoid false positives like "sur le PID 1234"
        r"(?:info(?:rmations?)?|details?|détails?)\s+(?:on|about|sur|de)\s+@(\w[\w.-]*)",
        r"^@(\w[\w.-]*)\s*$",  # Just a host mention
    ],
    "group.list": [
        r"^(?:liste?|show)\s+(?:les?\s+)?(?:groups?|groupes?|tags?)",
        r"^(?:quels?\s+sont\s+)?(?:mes?\s+)?(?:groups?|groupes?)",
    ],
    "skill.list": [
        r"^(?:liste?|show)\s+(?:les?\s+)?skills?",
        r"^(?:quelles?\s+skills?|what\s+skills?)",
    ],
    "var.list": [
        r"^(?:liste?|show)\s+(?:les?\s+)?(?:variables?|vars?)",
    ],
    "var.get": [
        r"(?:valeur|value)\s+(?:de|of)\s+@?(\w[\w_.-]*)",
    ],
}

# Mode to tool calls limit mapping
MODE_TOOL_LIMITS: dict[AgentMode, int] = {
    AgentMode.DIAGNOSTIC: TOOL_CALLS_LIMIT_DIAGNOSTIC,
    AgentMode.REMEDIATION: TOOL_CALLS_LIMIT_REMEDIATION,
    AgentMode.QUERY: TOOL_CALLS_LIMIT_QUERY,
    AgentMode.CHAT: TOOL_CALLS_LIMIT_CHAT,
}

# Mode to request limit mapping
MODE_REQUEST_LIMITS: dict[AgentMode, int] = {
    AgentMode.DIAGNOSTIC: REQUEST_LIMIT_DIAGNOSTIC,
    AgentMode.REMEDIATION: REQUEST_LIMIT_REMEDIATION,
    AgentMode.QUERY: REQUEST_LIMIT_QUERY,
    AgentMode.CHAT: REQUEST_LIMIT_CHAT,
}


def tool_calls_limit_for(mode: AgentMode) -> int:
    return MODE_TOOL_LIMITS.get(mode, DEFAULT_TOOL_CALLS_LIMIT)


def request_limit_for(mode: AgentMode) -> int:
    return MODE_REQUEST_LIMITS.get(mode, DEFAULT_REQUEST_LIMIT)


# Patterns to detect jump host intent (multilingual)
# These patterns look for "via/through/par/depuis + @hostname or hostname"
JUMP_HOST_PATTERNS = [
    # English
    r"\bvia\s+(?:the\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\bthrough\s+(?:the\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\busing\s+(?:the\s+)?(?:bastion|jump\s*host?)\s+@?(\w[\w.-]*)",
    # French
    r"\bvia\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\ben\s+passant\s+par\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\bà\s+travers\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\bdepuis\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    # Generic bastion/jump patterns
    r"\bbastion\s*[=:]\s*@?(\w[\w.-]*)",
    r"\bjump\s*host?\s*[=:]\s*@?(\w[\w.-]*)",
]


# Pre-compiled fast path patterns for performance
_COMPILED_FAST_PATH: dict[str, list[re.Pattern[str]]] = {}


def _compile_fast_path_patterns() -> None:
    """Compile fast path patterns once at import time."""
    global _COMPILED_FAST_PATH
    if _COMPILED_FAST_PATH:
        return
    for intent, patterns in FAST_PATH_PATTERNS.items():
        _COMPILED_FAST_PATH[intent] = [re.compile(p, re.IGNORECASE) for p in patterns]


def iter_fast_path_patterns() -> dict[str, list[re.Pattern[str]]]:
    """Return compiled patterns (compiles on first use)."""
    _compile_fast_path_patterns()
    return _COMPILED_FAST_PATH


def extract_json_dict(text: str) -> dict[str, Any] | None:
    """
    Best-effort extraction of a JSON object from an LLM string response.

    Handles common wrappers like Markdown fences:
    ```json
    {...}
    ```
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


# Compile patterns at module load
_compile_fast_path_patterns()


__all__ = [
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    "JUMP_HOST_PATTERNS",
    "MODE_REQUEST_LIMITS",
    "MODE_TOOL_LIMITS",
    "_LLMClassification",
    "_LLMSkillMatch",
    "extract_json_dict",
    "iter_fast_path_patterns",
    "request_limit_for",
    "tool_calls_limit_for",
]
