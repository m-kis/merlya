"""
Merlya Router - Compiled regex patterns for fast path detection.

Contains pre-compiled patterns for intent detection.
"""

from __future__ import annotations

from merlya.router.router_primitives import (
    FAST_PATH_INTENTS,
    FAST_PATH_PATTERNS,
    JUMP_HOST_PATTERNS,
    iter_fast_path_patterns,
)

# Backward compatibility: tests and older code imported this symbol from classifier.py.
_COMPILED_FAST_PATH = iter_fast_path_patterns()

__all__ = [
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    "JUMP_HOST_PATTERNS",
    "_COMPILED_FAST_PATH",
    "iter_fast_path_patterns",
]
