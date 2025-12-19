"""
Merlya Agent - History processors for conversation management.

Simplified version that focuses on:
- Tool call/return pairing validation
- Context window limiting
- Simple tool call limit (no complex pattern detection)
"""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.messages import (
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from merlya.config.constants import HARD_MAX_HISTORY_MESSAGES

# Simple guardrail: max tool calls since last user message
# This prevents runaway loops without complex pattern detection
# NOTE: Must be LOWER than DEFAULT_TOOL_CALLS_LIMIT (50) to fire before failsafe
MAX_TOOL_CALLS_SINCE_LAST_USER = 25

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
            for part in msg.parts:  # type: ignore[assignment]
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    return_ids.add(part.tool_call_id)

    orphan_calls = call_ids - return_ids
    orphan_returns = return_ids - call_ids

    if orphan_calls:
        logger.debug(f"Orphan tool calls found: {orphan_calls}")
    if orphan_returns:
        logger.debug(f"Orphan tool returns found: {orphan_returns}")

    return not orphan_calls and not orphan_returns


def find_safe_truncation_point(
    messages: list[ModelMessage],
    max_messages: int,
) -> int:
    """
    Find a safe truncation point that preserves tool call/return pairs.

    This function ensures that no ToolReturnPart appears without its
    corresponding ToolCallPart after truncation. This is critical because
    some LLM APIs (like Mistral) reject messages with orphaned tool returns.

    Args:
        messages: List of ModelMessage to analyze.
        max_messages: Maximum number of messages to keep.

    Returns:
        Index from which to keep messages (0 = keep all).
    """
    if len(messages) <= max_messages:
        return 0

    start_idx = len(messages) - max_messages

    # Collect ALL tool call IDs BEFORE the truncation point (will be discarded)
    calls_before: set[str] = set()
    for i in range(start_idx):
        msg = messages[i]
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    calls_before.add(part.tool_call_id)

    # Collect ALL tool call IDs AFTER the truncation point (will be kept)
    calls_after: set[str] = set()
    for i in range(start_idx, len(messages)):
        msg = messages[i]
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart) and part.tool_call_id:
                    calls_after.add(part.tool_call_id)

    # Collect ALL tool return IDs AFTER the truncation point
    returns_after: set[str] = set()
    for i in range(start_idx, len(messages)):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            for part in msg.parts:  # type: ignore[assignment]
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    returns_after.add(part.tool_call_id)

    # Find orphaned returns: returns that have NO corresponding call after truncation
    # These would cause "Unexpected tool call id" errors from the LLM API
    orphaned_returns = returns_after - calls_after

    # Find orphaned calls: calls before truncation whose returns are after
    orphaned_calls = calls_before & returns_after

    # All orphan IDs that need their messages included
    all_orphans = orphaned_calls | orphaned_returns

    if not all_orphans:
        return start_idx

    logger.debug(f"Found orphaned tool IDs: {all_orphans}, moving truncation point")

    # Move truncation point earlier to include all orphaned tool calls
    for i in range(start_idx - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                is_orphaned = (
                    isinstance(part, ToolCallPart)
                    and part.tool_call_id
                    and part.tool_call_id in all_orphans
                )
                if is_orphaned:
                    assert isinstance(part, ToolCallPart)
                    all_orphans.discard(part.tool_call_id)
                    if not all_orphans:
                        return i

    # Fallback: hard limit
    if len(messages) > HARD_MAX_HISTORY_MESSAGES:
        logger.warning(f"Applying hard limit ({HARD_MAX_HISTORY_MESSAGES} messages)")
        return len(messages) - HARD_MAX_HISTORY_MESSAGES

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
        logger.debug(f"History truncated: kept {len(truncated)}/{len(messages)} messages")

    return truncated


def get_tool_call_count(messages: list[ModelMessage]) -> int:
    """Count total tool calls in message history."""
    count = 0
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    count += 1
    return count


def get_user_message_count(messages: list[ModelMessage]) -> int:
    """Count user messages in history."""
    count = 0
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    count += 1
    return count


def _find_last_user_message_index(messages: list[ModelMessage]) -> int:
    """Find the index of the last user message."""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    return i
    return 0


def _count_tool_calls_since_user(messages: list[ModelMessage]) -> int:
    """Count tool calls since the last user message."""
    last_user_idx = _find_last_user_message_index(messages)
    count = 0
    for msg in messages[last_user_idx:]:
        if isinstance(msg, ModelResponse):
            count += sum(1 for part in msg.parts if isinstance(part, ToolCallPart))
    return count


def create_history_processor(max_messages: int = 20) -> HistoryProcessor:
    """
    Create a simple history processor.

    Args:
        max_messages: Maximum messages to retain.

    Returns:
        A callable that truncates history with tool pairs preserved.
    """

    def processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        return limit_history(messages, max_messages=max_messages)

    return processor


def create_loop_aware_history_processor(
    max_messages: int = 20,
    enable_loop_detection: bool = True,
) -> HistoryProcessor:
    """
    Create a history processor with simple tool call limiting.

    This processor:
    1. Checks if too many tool calls happened since last user message
    2. If so, injects a message asking the agent to change approach
    3. Truncates history while preserving tool call/return pairs

    Args:
        max_messages: Maximum messages to retain.
        enable_loop_detection: Whether to check for excessive tool calls.

    Returns:
        A callable history processor for PydanticAI agent.
    """

    def processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        result = messages

        if enable_loop_detection:
            tool_calls = _count_tool_calls_since_user(messages)
            if tool_calls >= MAX_TOOL_CALLS_SINCE_LAST_USER:
                logger.warning(f"Too many tool calls ({tool_calls}), injecting guidance")
                breaker = ModelRequest(
                    parts=[
                        UserPromptPart(
                            content=(
                                f"You have made {tool_calls} tool calls without completing the task. "
                                "STOP and reassess: What is the core issue? "
                                "Try a completely different approach or report what you've learned."
                            )
                        )
                    ]
                )
                result = [*messages, breaker]

        return limit_history(result, max_messages=max_messages)

    return processor
