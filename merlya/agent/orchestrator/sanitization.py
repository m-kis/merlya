"""
Input sanitization for the orchestrator.

Contains security-related input validation functions.
"""

from __future__ import annotations

import re

from loguru import logger

from .constants import INJECTION_PATTERNS
from .models import SecurityError


def sanitize_user_input(user_input: str) -> str:
    """
    Sanitize user input before delegation.

    Args:
        user_input: Raw user input.

    Returns:
        Sanitized input.

    Raises:
        SecurityError: If injection patterns detected.
    """
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, user_input, re.IGNORECASE):
            logger.warning(f"Potential injection detected: {pattern}")
            raise SecurityError(
                "Input contains potentially unsafe patterns. Please rephrase your request."
            )
    return user_input
