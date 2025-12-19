"""
Merlya Tools - User interaction.

Ask questions and request confirmations from user.

Includes deduplication to prevent infinite loops when LLM
repeatedly asks the same question.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core.models import ToolResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Maximum times the same question can be asked before returning cached answer
MAX_SAME_QUESTION = 2


def _question_fingerprint(question: str, choices: list[str] | None = None) -> str:
    """Generate a fingerprint for a question to detect duplicates."""
    # Normalize: lowercase, strip whitespace, include choices
    normalized = question.lower().strip()
    if choices:
        normalized += "|" + "|".join(sorted(c.lower() for c in choices))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


async def ask_user(
    ctx: SharedContext,
    question: str,
    choices: list[str] | None = None,
    default: str | None = None,
    secret: bool = False,
) -> ToolResult:
    """
    Ask the user for input.

    Includes deduplication: if the same question is asked multiple times,
    returns the cached answer instead of re-prompting the user.

    Args:
        ctx: Shared context.
        question: Question to ask.
        choices: Optional list of choices.
        default: Default value.
        secret: Whether to hide input.

    Returns:
        ToolResult with user response.
    """
    # Validate question
    if not question or not question.strip():
        return ToolResult(
            success=False,
            data=None,
            error="Question cannot be empty",
        )

    # Check for duplicate questions (loop detection)
    fingerprint = _question_fingerprint(question, choices)

    # Initialize question cache on context if not present
    if not hasattr(ctx, "_ask_user_cache"):
        ctx._ask_user_cache = {}  # type: ignore[attr-defined]
    if not hasattr(ctx, "_ask_user_counts"):
        ctx._ask_user_counts = {}  # type: ignore[attr-defined]

    # Track question count
    ctx._ask_user_counts[fingerprint] = ctx._ask_user_counts.get(fingerprint, 0) + 1  # type: ignore[attr-defined]
    count = ctx._ask_user_counts[fingerprint]  # type: ignore[attr-defined]

    # If question was asked before and we have a cached answer, return it
    if fingerprint in ctx._ask_user_cache:  # type: ignore[attr-defined]
        cached_response = ctx._ask_user_cache[fingerprint]  # type: ignore[attr-defined]
        if count > MAX_SAME_QUESTION:
            short_q = question[:30] + "..." if len(question) > 30 else question
            short_r = str(cached_response)[:20]
            logger.warning(
                f"🔄 Question asked {count}x, returning cached answer: '{short_q}' → '{short_r}'"
            )
            return ToolResult(
                success=True,
                data=cached_response,
                error=None,
            )

    try:
        ui = ctx.ui

        if secret:
            response = await ui.prompt_secret(question)
        elif choices:
            response = await ui.prompt_choice(question, choices, default)
        else:
            response = await ui.prompt(question, default or "")

        # Cache the response (don't cache secrets)
        if not secret:
            ctx._ask_user_cache[fingerprint] = response  # type: ignore[attr-defined]

        return ToolResult(success=True, data=response)

    except Exception as e:
        logger.error(f"❌ Failed to get user input: {e}")
        return ToolResult(success=False, data=None, error=str(e))


async def request_confirmation(
    ctx: SharedContext,
    action: str,
    details: str | None = None,
    risk_level: str = "moderate",
) -> ToolResult:
    """
    Request user confirmation before an action.

    Args:
        ctx: Shared context.
        action: Description of the action.
        details: Additional details.
        risk_level: Risk level (low, moderate, high, critical).

    Returns:
        ToolResult with confirmation (True/False).
    """
    # Validate action
    if not action or not action.strip():
        return ToolResult(
            success=False,
            data=False,
            error="Action description cannot be empty",
        )

    try:
        ui = ctx.ui

        # Format message based on risk
        risk_icons = {
            "low": "",
            "moderate": "",
            "high": "",
            "critical": "",
        }
        icon = risk_icons.get(risk_level, "")

        message = f"{icon} {action}"
        if details:
            ui.info(f"   {details}")

        confirmed = await ui.prompt_confirm(message, default=False)

        return ToolResult(success=True, data=confirmed)

    except Exception as e:
        logger.error(f"❌ Failed to get confirmation: {e}")
        return ToolResult(success=False, data=False, error=str(e))


# Shims to interaction.py for credential/elevation tools
async def request_credentials(*args: Any, **kwargs: Any) -> ToolResult:  # pragma: no cover
    """Request credentials from user (delegated to interaction.py)."""
    from merlya.tools.interaction import request_credentials as _rc

    return await _rc(*args, **kwargs)  # type: ignore[return-value]


async def request_elevation(*args: Any, **kwargs: Any) -> ToolResult:  # pragma: no cover
    """Request privilege elevation (delegated to interaction.py)."""
    from merlya.tools.interaction import request_elevation as _re

    return await _re(*args, **kwargs)  # type: ignore[return-value]
