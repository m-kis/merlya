"""
Merlya Agent - History processors for conversation management.

Provides tools for managing message history, including:
- Tool call/return pairing validation
- Context window limiting
- History truncation with integrity checks
- Loop detection to prevent repetitive tool calls
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from typing import Any

from loguru import logger
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.messages import (
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from merlya.config.constants import HARD_MAX_HISTORY_MESSAGES

# Loop detection thresholds
LOOP_DETECTION_WINDOW = 10  # Look at last N tool calls
LOOP_THRESHOLD_SAME_CALL = 3  # Same tool+args called N times = loop
LOOP_THRESHOLD_PATTERN = 4  # Same 2-3 tool alternation pattern
MAX_TOOL_CALLS_SINCE_LAST_USER = 50  # Prevent command explosions per user request

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
            for part in msg.parts:  # type: ignore[assignment]
                if isinstance(part, ToolReturnPart) and part.tool_call_id:
                    # Return also before truncation, remove from tracking
                    calls_before.discard(part.tool_call_id)

    # Collect tool return IDs AFTER (or at) the truncation point
    returns_after: set[str] = set()
    for i in range(start_idx, len(messages)):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            for part in msg.parts:  # type: ignore[assignment]
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
                    assert isinstance(part, ToolCallPart)
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


def _compute_tool_signature(tool_name: str, args: dict[str, Any] | str | None) -> str:
    """
    Compute a signature for a tool call (name + args hash).

    Args:
        tool_name: Name of the tool.
        args: Tool arguments (dict or JSON string).

    Returns:
        A short hash signature for the tool call.
    """
    if args is None:
        args_str = ""
    elif isinstance(args, str):
        args_str = args
    else:
        # Sort keys for deterministic hash
        args_str = json.dumps(args, sort_keys=True, default=str)

    combined = f"{tool_name}:{args_str}"
    return hashlib.md5(combined.encode(), usedforsecurity=False).hexdigest()[:12]


def extract_recent_tool_signatures(
    messages: list[ModelMessage],
    window: int = LOOP_DETECTION_WINDOW,
) -> list[tuple[str, str]]:
    """
    Extract recent tool call signatures from message history.

    Args:
        messages: Message history to analyze.
        window: Number of recent tool calls to consider.

    Returns:
        List of (tool_name, signature) tuples, most recent last.
    """
    signatures: list[tuple[str, str]] = []

    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    sig = _compute_tool_signature(part.tool_name, part.args)
                    signatures.append((part.tool_name, sig))

    # Return only the last `window` calls
    return signatures[-window:] if len(signatures) > window else signatures


def _find_last_user_message_index(messages: list[ModelMessage]) -> int:
    """Find the index of the last real user message (not loop breaker)."""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                # Skip loop breaker messages
                if isinstance(part, UserPromptPart) and "LOOP DETECTED" not in part.content:
                    return i
    return 0


def _has_loop_breaker_since_last_user_message(messages: list[ModelMessage]) -> bool:
    """Check if a loop breaker was already injected since the last user message.

    When loading a conversation with old loops, we don't want to immediately
    re-trigger the loop breaker. This allows the user to try again after
    they send a new message.
    """
    last_user_idx = _find_last_user_message_index(messages)

    # Check messages AFTER the last user message for loop breaker
    for msg in messages[last_user_idx + 1 :]:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and "LOOP DETECTED" in part.content:
                    return True
    return False


def detect_loop(
    messages: list[ModelMessage],
    threshold_same: int = LOOP_THRESHOLD_SAME_CALL,
    threshold_pattern: int = LOOP_THRESHOLD_PATTERN,
) -> tuple[bool, str | None]:
    """
    Detect if the agent is stuck in a loop.

    Detects three types of loops:
    1. Same exact tool+args called N times (total in window)
    2. Last N calls are all identical (consecutive)
    3. Alternating pattern (A-B-A-B or A-B-C-A-B-C)

    Only considers tool calls made AFTER the last user message to avoid
    false positives when loading conversations with old repetitive patterns.

    Args:
        messages: Message history to analyze.
        threshold_same: Number of identical calls to trigger loop detection.
        threshold_pattern: Number of pattern repetitions to trigger.

    Returns:
        Tuple of (is_loop, description).
    """
    # Skip if we already injected a loop breaker since last user message
    # This prevents re-triggering within the same user request
    if _has_loop_breaker_since_last_user_message(messages):
        return False, None

    # Only analyze messages AFTER the last user message
    # This prevents false positives from old repetitive calls in loaded conversations
    last_user_idx = _find_last_user_message_index(messages)
    recent_messages = messages[last_user_idx:]

    # Guardrail: too many tool calls in a single user request (even if not repetitive)
    tool_calls_since_user = 0
    for msg in recent_messages:
        if isinstance(msg, ModelResponse):
            tool_calls_since_user += sum(1 for part in msg.parts if isinstance(part, ToolCallPart))

    if tool_calls_since_user >= MAX_TOOL_CALLS_SINCE_LAST_USER:
        return True, f"Too many tool calls ({tool_calls_since_user}) since last user message"

    signatures = extract_recent_tool_signatures(recent_messages)

    if len(signatures) < threshold_same:
        return False, None

    # Check 1: Last N calls are ALL identical (consecutive loop - most aggressive)
    consecutive_threshold = min(threshold_same, 3)  # At least 3 consecutive
    if len(signatures) >= consecutive_threshold:
        last_n = signatures[-consecutive_threshold:]
        if len({sig for _, sig in last_n}) == 1:
            tool_name = last_n[0][0]
            return (
                True,
                f"Same tool call '{tool_name}' repeated {consecutive_threshold}+ times consecutively",
            )

    # Check 2: Same exact call repeated (total count in window)
    sig_counter = Counter(sig for _, sig in signatures)
    most_common_sig, count = sig_counter.most_common(1)[0]

    if count >= threshold_same:
        # Find tool name for this signature
        tool_name = next(name for name, sig in signatures if sig == most_common_sig)
        return True, f"Same tool call '{tool_name}' repeated {count} times"

    # Check 3: Alternating patterns (A-B-A-B or similar)
    if len(signatures) >= threshold_pattern * 2:
        # Check 2-element pattern (A-B-A-B)
        last_sigs = [sig for _, sig in signatures[-threshold_pattern * 2 :]]
        pattern_2 = last_sigs[:2]
        if len(pattern_2) == 2 and pattern_2[0] != pattern_2[1]:
            is_pattern = all(last_sigs[i] == pattern_2[i % 2] for i in range(len(last_sigs)))
            if is_pattern:
                tools = [name for name, _ in signatures[-threshold_pattern * 2 :]]
                unique_tools = list(dict.fromkeys(tools))[:2]
                return True, f"Alternating loop between '{unique_tools[0]}' and '{unique_tools[1]}'"

    return False, None


def inject_loop_breaker(
    messages: list[ModelMessage],
    loop_description: str,
) -> list[ModelMessage]:
    """
    Inject a user message to help the agent break out of a loop.

    Uses UserPromptPart instead of SystemPromptPart because some providers
    (like Mistral) don't allow system messages after tool responses.

    Args:
        messages: Current message history.
        loop_description: Description of the detected loop.

    Returns:
        Modified message history with loop breaker appended.
    """
    breaker_text = (
        f"⚠️ LOOP DETECTED: {loop_description}. "
        "You are repeating the same actions without progress. "
        "STOP and try a DIFFERENT approach: "
        "1) If a command fails, explain WHY it failed and suggest alternatives. "
        "2) If you need information you can't get, ask the user. "
        "3) Do NOT retry the same command with the same arguments."
    )

    logger.warning(f"🔄 {loop_description} - injecting loop breaker")

    # Append as a new ModelRequest with UserPromptPart
    # This is safer than injecting into existing requests with ToolReturnParts
    modified = list(messages)
    modified.append(ModelRequest(parts=[UserPromptPart(content=breaker_text)]))

    return modified


def create_loop_aware_history_processor(
    max_messages: int = 20,
    enable_loop_detection: bool = True,
) -> HistoryProcessor:
    """
    Create a history processor with loop detection.

    This processor:
    1. Detects repetitive tool call patterns
    2. Injects a "loop breaker" message when loops are detected
    3. Truncates history while preserving tool call/return pairs

    Args:
        max_messages: Maximum messages to retain.
        enable_loop_detection: Whether to detect and break loops.

    Returns:
        A callable history processor for PydanticAI agent.

    Example:
        >>> processor = create_loop_aware_history_processor(max_messages=30)
        >>> agent = Agent(model, history_processors=[processor])
    """

    def processor(messages: list[ModelMessage]) -> list[ModelMessage]:
        """Process message history with loop detection."""
        result = messages

        # Check for loops before truncation (to see full pattern)
        if enable_loop_detection:
            is_loop, description = detect_loop(messages)
            if is_loop and description:
                result = inject_loop_breaker(result, description)

        # Then truncate
        return limit_history(result, max_messages=max_messages)

    return processor
