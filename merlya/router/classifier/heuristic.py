"""
Merlya Router - Heuristic classification (fast path without LLM).

Contains fast-path detection and regex-based classification.
"""

from __future__ import annotations

import re

from loguru import logger

from merlya.router.router_primitives import (
    JUMP_HOST_PATTERNS,
    iter_fast_path_patterns,
)


def validate_identifier(name: str) -> bool:
    """Validate that an identifier is safe (hostname, variable name, etc.).

    Prevents path traversal and injection attacks.
    """
    if not name or len(name) > 255:
        return False
    # Must start with alphanumeric, contain only safe chars
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", name):
        return False
    # Reject path traversal attempts
    return ".." not in name


def detect_fast_path(text: str) -> tuple[str | None, dict[str, str]]:
    """
    Detect fast path intent from user input.

    Args:
        text: User input text.

    Returns:
        Tuple of (intent_name, extracted_args) or (None, {}) if no match.
    """
    text_stripped = text.strip()

    for intent, patterns in iter_fast_path_patterns().items():
        for pattern in patterns:
            match = pattern.search(text_stripped)
            if match:
                # Extract named groups or positional groups as args
                args: dict[str, str] = {}
                if match.groups():
                    target = match.group(1)
                    # P0 Security: Validate identifier before using
                    if not validate_identifier(target):
                        logger.warning(f"Invalid target identifier: {target[:50]}")
                        continue  # Skip this pattern, try next
                    args["target"] = target
                return intent, args

    return None, {}


def detect_jump_host(text: str) -> str | None:
    """
    Detect jump/bastion host from user input.

    Looks for patterns like:
    - "via @ansible" / "via ansible"
    - "through the bastion"
    - "en passant par @jump-host"

    Args:
        text: User input text.

    Returns:
        Jump host name if detected, None otherwise.
    """
    text_lower = text.lower()

    for pattern in JUMP_HOST_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            jump_host = match.group(1)
            # Filter out common false positives
            if jump_host and jump_host not in ("the", "la", "le", "machine", "host"):
                return jump_host

    return None


__all__ = [
    "detect_fast_path",
    "detect_jump_host",
    "validate_identifier",
]
