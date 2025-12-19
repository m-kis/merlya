"""Tests for merlya.agent.history module (simplified version)."""

from pydantic_ai import ModelRequest, ModelResponse
from pydantic_ai.messages import (
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from merlya.agent.history import (
    create_history_processor,
    create_loop_aware_history_processor,
    find_safe_truncation_point,
    get_tool_call_count,
    get_user_message_count,
    limit_history,
    validate_tool_pairing,
)


def _make_user_request(content: str) -> ModelRequest:
    """Create a simple user request message."""
    return ModelRequest(parts=[UserPromptPart(content=content)])


def _make_assistant_response(content: str) -> ModelResponse:
    """Create a simple assistant response message."""
    return ModelResponse(parts=[TextPart(content=content)])


def _make_tool_call(tool_call_id: str, tool_name: str = "test_tool") -> ModelResponse:
    """Create an assistant response with a tool call."""
    return ModelResponse(
        parts=[ToolCallPart(tool_call_id=tool_call_id, tool_name=tool_name, args={})]
    )


def _make_tool_return(tool_call_id: str, content: str = "result") -> ModelRequest:
    """Create a request with a tool return."""
    return ModelRequest(
        parts=[ToolReturnPart(tool_call_id=tool_call_id, tool_name="test_tool", content=content)]
    )


class TestValidateToolPairing:
    """Tests for validate_tool_pairing function."""

    def test_empty_history_is_valid(self) -> None:
        """Empty message list should be valid."""
        assert validate_tool_pairing([]) is True

    def test_no_tool_calls_is_valid(self) -> None:
        """Messages without tool calls should be valid."""
        messages = [
            _make_user_request("hello"),
            _make_assistant_response("hi there"),
        ]
        assert validate_tool_pairing(messages) is True

    def test_paired_tool_calls_are_valid(self) -> None:
        """Tool calls with matching returns should be valid."""
        messages = [
            _make_user_request("do something"),
            _make_tool_call("call_1"),
            _make_tool_return("call_1"),
            _make_assistant_response("done"),
        ]
        assert validate_tool_pairing(messages) is True

    def test_multiple_paired_calls_are_valid(self) -> None:
        """Multiple tool calls all with returns should be valid."""
        messages = [
            _make_user_request("do stuff"),
            _make_tool_call("call_1"),
            _make_tool_return("call_1"),
            _make_tool_call("call_2"),
            _make_tool_return("call_2"),
            _make_assistant_response("all done"),
        ]
        assert validate_tool_pairing(messages) is True

    def test_orphan_call_is_invalid(self) -> None:
        """Tool call without return should be invalid."""
        messages = [
            _make_user_request("do something"),
            _make_tool_call("call_1"),
            _make_assistant_response("failed"),
        ]
        assert validate_tool_pairing(messages) is False

    def test_orphan_return_is_invalid(self) -> None:
        """Tool return without call should be invalid."""
        messages = [
            _make_user_request("do something"),
            _make_tool_return("call_1"),
            _make_assistant_response("done"),
        ]
        assert validate_tool_pairing(messages) is False


class TestFindSafeTruncationPoint:
    """Tests for find_safe_truncation_point function."""

    def test_small_history_returns_zero(self) -> None:
        """History smaller than max should return 0 (keep all)."""
        messages = [
            _make_user_request("hello"),
            _make_assistant_response("hi"),
        ]
        assert find_safe_truncation_point(messages, max_messages=10) == 0

    def test_exact_size_returns_zero(self) -> None:
        """History exactly at max should return 0."""
        messages = [
            _make_user_request("hello"),
            _make_assistant_response("hi"),
        ]
        assert find_safe_truncation_point(messages, max_messages=2) == 0

    def test_truncation_without_tools(self) -> None:
        """Simple truncation without tool calls."""
        messages = [
            _make_user_request("msg1"),
            _make_assistant_response("resp1"),
            _make_user_request("msg2"),
            _make_assistant_response("resp2"),
            _make_user_request("msg3"),
            _make_assistant_response("resp3"),
        ]
        # Keep last 2: should start at index 4
        assert find_safe_truncation_point(messages, max_messages=2) == 4

    def test_truncation_preserves_tool_pairs(self) -> None:
        """Truncation should move earlier to preserve tool call/return pairs."""
        messages = [
            _make_user_request("msg1"),  # 0
            _make_assistant_response("resp1"),  # 1
            _make_tool_call("call_1"),  # 2 - call before truncation
            _make_tool_return("call_1"),  # 3 - return after truncation
            _make_user_request("msg2"),  # 4
            _make_assistant_response("resp2"),  # 5
        ]
        # max_messages=3 would start at index 3, but call_1 is at index 2
        # Should move to index 2 to include the call
        result = find_safe_truncation_point(messages, max_messages=3)
        assert result == 2

    def test_truncation_with_complete_pair_before(self) -> None:
        """Tool pair entirely before truncation should not affect result."""
        messages = [
            _make_user_request("msg1"),  # 0
            _make_tool_call("call_1"),  # 1
            _make_tool_return("call_1"),  # 2 - complete pair before
            _make_user_request("msg2"),  # 3
            _make_assistant_response("resp2"),  # 4
            _make_user_request("msg3"),  # 5
            _make_assistant_response("resp3"),  # 6
        ]
        # max_messages=2 starts at index 5, no orphaned calls
        assert find_safe_truncation_point(messages, max_messages=2) == 5

    def test_truncation_preserves_orphaned_returns(self) -> None:
        """Truncation should move earlier to include calls for orphaned returns.

        This tests the fix for the Mistral API error:
        "Unexpected tool call id POrAwIYLx in tool results"

        When truncating history, if a ToolReturnPart exists after the truncation
        point but its corresponding ToolCallPart is before the truncation point,
        we must include the call to avoid API errors.
        """
        messages = [
            _make_user_request("msg1"),  # 0
            _make_tool_call("call_A"),  # 1 - call that would be discarded
            _make_user_request("msg2"),  # 2
            _make_tool_call("call_B"),  # 3 - call that would be discarded
            _make_tool_return("call_A"),  # 4 - return for discarded call
            _make_tool_return("call_B"),  # 5 - return for discarded call
            _make_user_request("msg3"),  # 6
            _make_assistant_response("resp3"),  # 7
        ]
        # max_messages=4 would start at index 4
        # But call_A (at 1) and call_B (at 3) have returns at 4 and 5
        # Should move to include both calls
        result = find_safe_truncation_point(messages, max_messages=4)
        # Must include call_A at index 1
        assert result <= 1

        # Verify the truncated history has valid pairing
        truncated = messages[result:]
        assert validate_tool_pairing(truncated) is True


class TestLimitHistory:
    """Tests for limit_history function."""

    def test_small_history_unchanged(self) -> None:
        """History under limit should be unchanged."""
        messages = [
            _make_user_request("hello"),
            _make_assistant_response("hi"),
        ]
        result = limit_history(messages, max_messages=10)
        assert len(result) == 2
        assert result == messages

    def test_truncates_to_max(self) -> None:
        """History should be truncated to max_messages."""
        messages = [
            _make_user_request(f"msg{i}") if i % 2 == 0 else _make_assistant_response(f"resp{i}")
            for i in range(10)
        ]
        result = limit_history(messages, max_messages=4)
        assert len(result) == 4

    def test_preserves_tool_integrity(self) -> None:
        """Truncation should preserve tool call/return integrity."""
        messages = [
            _make_user_request("old"),  # 0
            _make_assistant_response("old_resp"),  # 1
            _make_tool_call("call_1"),  # 2
            _make_tool_return("call_1"),  # 3
            _make_user_request("new"),  # 4
            _make_assistant_response("new_resp"),  # 5
        ]
        result = limit_history(messages, max_messages=3)
        # Should validate after truncation
        assert validate_tool_pairing(result) is True


class TestCreateHistoryProcessor:
    """Tests for create_history_processor factory function."""

    def test_returns_callable(self) -> None:
        """Factory should return a callable."""
        processor = create_history_processor(max_messages=10)
        assert callable(processor)

    def test_processor_limits_history(self) -> None:
        """Processor should limit history to max_messages."""
        processor = create_history_processor(max_messages=2)
        messages = [
            _make_user_request("msg1"),
            _make_assistant_response("resp1"),
            _make_user_request("msg2"),
            _make_assistant_response("resp2"),
        ]
        result = processor(messages)
        assert len(result) == 2


class TestGetToolCallCount:
    """Tests for get_tool_call_count function."""

    def test_empty_history_returns_zero(self) -> None:
        """Empty history should return 0."""
        assert get_tool_call_count([]) == 0

    def test_no_tools_returns_zero(self) -> None:
        """History without tools should return 0."""
        messages = [
            _make_user_request("hello"),
            _make_assistant_response("hi"),
        ]
        assert get_tool_call_count(messages) == 0

    def test_counts_tool_calls(self) -> None:
        """Should count tool calls correctly."""
        messages = [
            _make_user_request("do stuff"),
            _make_tool_call("call_1"),
            _make_tool_return("call_1"),
            _make_tool_call("call_2"),
            _make_tool_return("call_2"),
            _make_assistant_response("done"),
        ]
        assert get_tool_call_count(messages) == 2


class TestGetUserMessageCount:
    """Tests for get_user_message_count function."""

    def test_empty_history_returns_zero(self) -> None:
        """Empty history should return 0."""
        assert get_user_message_count([]) == 0

    def test_counts_user_messages(self) -> None:
        """Should count user messages correctly."""
        messages = [
            _make_user_request("hello"),
            _make_assistant_response("hi"),
            _make_user_request("how are you"),
            _make_assistant_response("good"),
        ]
        assert get_user_message_count(messages) == 2

    def test_ignores_tool_returns(self) -> None:
        """Should not count tool returns as user messages."""
        messages = [
            _make_user_request("do stuff"),
            _make_tool_call("call_1"),
            _make_tool_return("call_1"),
            _make_assistant_response("done"),
        ]
        # Only 1 user message, tool return is not a user message
        assert get_user_message_count(messages) == 1


class TestCreateLoopAwareHistoryProcessor:
    """Tests for create_loop_aware_history_processor factory function."""

    def test_returns_callable(self) -> None:
        """Factory should return a callable."""
        processor = create_loop_aware_history_processor(max_messages=10)
        assert callable(processor)

    def test_processor_limits_history(self) -> None:
        """Processor should limit history to max_messages."""
        processor = create_loop_aware_history_processor(max_messages=2)
        messages = [
            _make_user_request("msg1"),
            _make_assistant_response("resp1"),
            _make_user_request("msg2"),
            _make_assistant_response("resp2"),
        ]
        result = processor(messages)
        assert len(result) == 2

    def test_no_breaker_when_disabled(self) -> None:
        """Processor should not inject breaker when detection disabled."""
        processor = create_loop_aware_history_processor(
            max_messages=50, enable_loop_detection=False
        )

        # Create many tool calls
        messages = [_make_user_request("do stuff")]
        for i in range(100):
            messages.append(_make_tool_call(f"call_{i}"))
            messages.append(_make_tool_return(f"call_{i}"))

        result = processor(messages)

        # Check that no breaker message was added (only truncation)
        has_breaker = False
        for msg in result:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart) and "tool calls" in part.content:
                        has_breaker = True
                        break

        assert not has_breaker, "Breaker should NOT be injected when disabled"

    def test_injects_breaker_at_threshold(self) -> None:
        """Processor should inject breaker at exactly MAX_TOOL_CALLS_SINCE_LAST_USER."""
        from merlya.agent.history import MAX_TOOL_CALLS_SINCE_LAST_USER

        processor = create_loop_aware_history_processor(max_messages=200)

        # Create exactly threshold number of tool calls
        messages: list = [_make_user_request("start")]
        for i in range(MAX_TOOL_CALLS_SINCE_LAST_USER):
            messages.append(_make_tool_call(f"call_{i}"))
            messages.append(_make_tool_return(f"call_{i}"))

        result = processor(messages)

        # Verify breaker was injected
        breaker_found = False
        for msg in result:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart) and "tool calls" in part.content:
                        breaker_found = True
                        break

        assert breaker_found, "Breaker should be injected at threshold"

    def test_no_breaker_below_threshold(self) -> None:
        """Processor should NOT inject breaker below threshold."""
        from merlya.agent.history import MAX_TOOL_CALLS_SINCE_LAST_USER

        processor = create_loop_aware_history_processor(max_messages=200)

        # Create one less than threshold
        messages: list = [_make_user_request("start")]
        for i in range(MAX_TOOL_CALLS_SINCE_LAST_USER - 1):
            messages.append(_make_tool_call(f"call_{i}"))
            messages.append(_make_tool_return(f"call_{i}"))

        result = processor(messages)

        # Verify NO breaker was injected
        breaker_found = False
        for msg in result:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart) and "tool calls" in part.content:
                        breaker_found = True
                        break

        assert not breaker_found, "Breaker should NOT be injected below threshold"
