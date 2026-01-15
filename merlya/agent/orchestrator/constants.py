"""
Orchestrator constants.

Contains limits, patterns, and configuration values used by the orchestrator.
"""

from __future__ import annotations

# Maximum retries for incomplete tasks
MAX_SPECIALIST_RETRIES = 3

# Tool call limits per specialist type
SPECIALIST_LIMITS = {
    "diagnostic": 40,
    "execution": 30,
    "security": 25,
    "query": 15,
}

# Injection patterns to detect
INJECTION_PATTERNS = [
    r"ignore (all |previous |your )?instructions",
    r"you are now",
    r"new instructions:",
    r"system prompt",
    r"<\|.*\|>",  # Special tokens
    r"forget (everything|all|what)",
    r"disregard (above|previous)",
]
