"""
Merlya Agent - History processors for conversation management.

Provides tools for managing message history, including:
- Tool call/return pairing validation
- Context window limiting
- History truncation with integrity checks
"""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.messages import (
    ToolCallPart,
    ToolReturnPart,
)

from merlya.config.constants import HARD_MAX_HISTORY_MESSAGES

# Type alias for history processor function
HistoryProcessor = Callable[[list[ModelMessage]], list[ModelMessage]]


def validate_tool_pairing(messages: list[ModelMessage]) -> bool:
    """
    Validate that all tool calls have matching returns.

    Args:
        messages: List of ModelMessage to validate.

    Returns:
        True if all tool calls are properly paired, False otherwise.
    """
    call_ids: set[str] = set()
    return_ids: set[str] = set()

    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    call_ids.add(part.tool_call_id)
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    return_ids.add(part.tool_call_id)

    orphan_calls = call_ids - return_ids
    orphan_returns = return_ids - call_ids

    if orphan_calls:
        logger.debug(f"⚠️ Orphan tool calls found: {orphan_calls}")
    if orphan_returns:
        logger.debug(f"⚠️ Orphan tool returns found: {orphan_returns}")

    return not orphan_calls and not orphan_returns


def find_safe_truncation_point(
    messages: list[ModelMessage],
    max_messages: int,
) -> int:
    """
    Find a safe truncation point that preserves tool call/return pairs.

    The algorithm:
    1. Find tool calls BEFORE the truncation point whose returns are AFTER
    2. Move the truncation point earlier to include those orphaned calls

    Args:
        messages: List of ModelMessage to analyze.
        max_messages: Maximum number of messages to keep.

    Returns:
        Index from which to keep messages (0 = keep all).
    """
    if len(messages) <= max_messages:
        return 0

    # Start from the desired truncation point
    start_idx = len(messages) - max_messages

    # Collect all tool call IDs BEFORE the truncation point
    calls_before: set[str] = set()
    for i in range(start_idx):
        msg = messages[i]
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    calls_before.add(part.tool_call_id)
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    # Return also before truncation, remove from tracking
                    calls_before.discard(part.tool_call_id)

    # Collect tool return IDs AFTER (or at) the truncation point
    returns_after: set[str] = set()
    for i in range(start_idx, len(messages)):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    returns_after.add(part.tool_call_id)

    # Find orphaned calls: calls before truncation with returns after
    orphaned_calls = calls_before & returns_after

    # If no orphaned calls, truncation point is safe
    if not orphaned_calls:
        return start_idx

    # Move truncation point earlier to include orphaned calls
    for i in range(start_idx - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                is_orphaned_call = (
                    isinstance(part, ToolCallPart)
                    and part.tool_call_id
                    and part.tool_call_id in orphaned_calls
                )
                if is_orphaned_call:
                    orphaned_calls.discard(part.tool_call_id)
                    if not orphaned_calls:
                        return i

    # Fallback: use hard limit to prevent unbounded growth
    # This may break tool pairs but prevents memory issues
    if len(messages) > HARD_MAX_HISTORY_MESSAGES:
        logger.warning(
            f"⚠️ Could not find safe truncation point, applying hard limit "
            f"({HARD_MAX_HISTORY_MESSAGES} messages)"
        )
        return len(messages) - HARD_MAX_HISTORY_MESSAGES

    logger.warning("⚠️ Could not find safe truncation point, keeping full history")
    return 0


def limit_history(
    messages: list[ModelMessage],
    max_messages: int = 20,
) -> list[ModelMessage]:
    """
    Limit message history while preserving tool call/return integrity.

    Args:
        messages: Full message history.
        max_messages: Maximum messages to retain.

    Returns:
        Truncated message history with tool pairs intact.
    """
    if len(messages) <= max_messages:
        return messages

    safe_start = find_safe_truncation_point(messages, max_messages)
    truncated = messages[safe_start:]

    if safe_start > 0:
        logger.debug(f"📋 History truncated: kept {len(truncated)}/{len(messages)} messages")

    return truncated


def create_history_processor(max_messages: int = 20) -> HistoryProcessor:
    """
    Create a history processor function for use with PydanticAI agent.

    Args:
        max_messages: Maximum messages to retain (default: 20).

    Returns:
        A callable that takes a list of ModelMessage and returns
        a truncated list with tool call/return pairs preserved.

    Example:
        >>> processor = create_history_processor(max_messages=30)
        >>> agent = Agent(model, history_processors=[processor])
    """

    def processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        """Process message history before sending to LLM."""
        return limit_history(messages, max_messages=max_messages)

    return processor


def get_tool_call_count(messages: list[ModelMessage]) -> int:
    """
    Count total tool calls in message history.

    Args:
        messages: Message history to analyze.

    Returns:
        Total number of tool calls.
    """
    count = 0
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    count += 1
    return count


def get_user_message_count(messages: list[ModelMessage]) -> int:
    """
    Count user messages in history.

    Args:
        messages: Message history to analyze.

    Returns:
        Number of user prompt parts.
    """
    from pydantic_ai.messages import UserPromptPart

    count = 0
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    count += 1
    return count
