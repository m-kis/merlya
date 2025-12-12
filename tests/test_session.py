"""
Tests for Session Manager functionality.

Tests TokenEstimator, ContextTierPredictor, SessionSummarizer, SessionManager.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from merlya.session.context_tier import (
    TIER_CONFIG,
    ComplexityFactors,
    ContextTier,
    ContextTierPredictor,
)
from merlya.session.summarizer import SessionSummarizer
from merlya.session.token_estimator import TokenEstimator


# Mock ModelMessage for testing
@dataclass
class MockMessage:
    """Mock message for testing."""

    kind: str
    content: str


class TestTokenEstimator:
    """Tests for TokenEstimator."""

    @pytest.fixture
    def estimator(self):
        """Create a token estimator."""
        return TokenEstimator(model="gpt-4")

    def test_estimate_empty_string(self, estimator):
        """Test estimating empty string."""
        assert estimator.estimate_tokens("") == 0

    def test_estimate_simple_text(self, estimator):
        """Test estimating simple text."""
        text = "Hello, this is a test message."
        tokens = estimator.estimate_tokens(text)
        # Should be > 0 and reasonable
        assert tokens > 0
        assert tokens < 100

    def test_estimate_code(self, estimator):
        """Test estimating code (should be denser)."""
        code = "```python\ndef hello():\n    print('hello')\n```"
        tokens = estimator.estimate_tokens(code)
        assert tokens > 0

    def test_estimate_json(self, estimator):
        """Test estimating JSON."""
        json_text = '{"key": "value", "number": 123, "array": [1, 2, 3]}'
        tokens = estimator.estimate_tokens(json_text)
        assert tokens > 0

    def test_estimate_messages(self, estimator):
        """Test estimating list of messages."""
        messages = [
            MockMessage(kind="user", content="Hello"),
            MockMessage(kind="assistant", content="Hi there!"),
        ]
        estimate = estimator.estimate_messages(messages)

        assert estimate.prompt_tokens > 0
        assert estimate.total_tokens >= estimate.prompt_tokens
        assert estimate.model == "gpt-4"

    def test_get_context_limit_known_model(self, estimator):
        """Test getting context limit for known model."""
        assert estimator.get_context_limit("gpt-4") == 8192
        assert estimator.get_context_limit("gpt-4-turbo") == 128000
        assert estimator.get_context_limit("claude-3-opus") == 200000

    def test_get_context_limit_unknown_model(self, estimator):
        """Test getting context limit for unknown model."""
        # Should return default
        limit = estimator.get_context_limit("unknown-model")
        assert limit == 8192

    def test_will_exceed_limit(self, estimator):
        """Test checking if content will exceed limit."""
        messages = [MockMessage(kind="user", content="Hello")]
        short_content = "Brief response"
        long_content = "x" * 100000  # Very long

        assert not estimator.will_exceed_limit(messages, short_content)
        assert estimator.will_exceed_limit(messages, long_content)


class TestContextTierPredictor:
    """Tests for ContextTierPredictor."""

    @pytest.fixture
    def predictor(self):
        """Create a predictor."""
        return ContextTierPredictor()

    def test_extract_factors_simple(self, predictor):
        """Test extracting factors from simple input."""
        factors = predictor.extract_factors("Hello, how are you?")

        assert factors.message_length > 0
        assert factors.word_count > 0
        assert not factors.has_logs
        assert not factors.has_code

    def test_extract_factors_with_logs(self, predictor):
        """Test extracting factors from input with logs."""
        text = "Error: connection failed\nException: timeout"
        factors = predictor.extract_factors(text)

        assert factors.has_logs

    def test_extract_factors_with_code(self, predictor):
        """Test extracting factors from input with code."""
        text = "Here's the code:\n```python\nprint('hello')\n```"
        factors = predictor.extract_factors(text)

        assert factors.has_code

    def test_extract_factors_with_json(self, predictor):
        """Test extracting factors from input with JSON."""
        text = 'Config: {"host": "localhost", "port": 8080}'
        factors = predictor.extract_factors(text)

        assert factors.has_json

    @pytest.mark.asyncio
    async def test_predict_simple_query(self, predictor):
        """Test predicting tier for simple query."""
        tier = await predictor.predict("List all hosts")

        # Simple query should be MINIMAL or STANDARD
        assert tier in (ContextTier.MINIMAL, ContextTier.STANDARD)

    @pytest.mark.asyncio
    async def test_predict_complex_query(self, predictor):
        """Test predicting tier for complex query."""
        text = """
        We have an incident on production servers.
        Error logs show multiple connection refused errors:
        ```
        ERROR 2024-01-15 10:30:00 - Connection refused to db-01
        ERROR 2024-01-15 10:30:01 - Connection refused to db-02
        ERROR 2024-01-15 10:30:02 - Timeout on web-01
        ```
        Multiple hosts affected: @web-01, @web-02, @db-01, @db-02
        This is blocking production traffic.
        """
        tier = await predictor.predict(text)

        # Complex incident should be STANDARD or EXTENDED
        assert tier in (ContextTier.STANDARD, ContextTier.EXTENDED)

    def test_tier_limits(self, predictor):
        """Test getting tier limits."""
        limits = predictor.get_tier_limits(ContextTier.MINIMAL)
        assert limits.max_messages == 10
        assert limits.max_tokens == 2000

        limits = predictor.get_tier_limits(ContextTier.EXTENDED)
        assert limits.max_messages == 100
        assert limits.max_tokens == 8000

    def test_should_summarize(self, predictor):
        """Test summarization check."""
        # Below threshold
        assert not predictor.should_summarize(
            ContextTier.STANDARD, current_messages=10, current_tokens=1000
        )

        # Above threshold
        assert predictor.should_summarize(
            ContextTier.STANDARD, current_messages=25, current_tokens=3500
        )

    def test_extract_factors_large_input_truncates(self, predictor):
        """Test that large input is truncated safely."""
        from merlya.session.context_tier import MAX_INPUT_SIZE

        # Create input larger than limit
        large_input = "x" * (MAX_INPUT_SIZE + 10000)
        factors = predictor.extract_factors(large_input)

        # Should be truncated to MAX_INPUT_SIZE
        assert factors.message_length == MAX_INPUT_SIZE

    def test_extract_factors_empty_input(self, predictor):
        """Test extracting factors from empty input."""
        factors = predictor.extract_factors("")
        assert factors.message_length == 0
        assert factors.word_count == 0

    def test_extract_factors_none_input(self, predictor):
        """Test extracting factors from None input."""
        factors = predictor.extract_factors(None)
        assert factors.message_length == 0
        assert factors.word_count == 0


class TestSessionSummarizer:
    """Tests for SessionSummarizer."""

    @pytest.fixture
    def summarizer(self):
        """Create a summarizer."""
        return SessionSummarizer(max_summary_tokens=200)

    @pytest.mark.asyncio
    async def test_summarize_empty(self, summarizer):
        """Test summarizing empty messages."""
        result = await summarizer.summarize([])

        assert result.summary == ""
        assert result.method == "empty"

    @pytest.mark.asyncio
    async def test_summarize_simple_messages(self, summarizer):
        """Test summarizing simple messages."""
        messages = [
            MockMessage(kind="user", content="Check status of @web-01"),
            MockMessage(kind="assistant", content="Host web-01 is healthy."),
            MockMessage(kind="user", content="Run df -h on @web-01"),
            MockMessage(kind="assistant", content="Disk usage: 45% on /dev/sda1"),
        ]

        result = await summarizer.summarize(messages)

        assert result.summary
        assert result.original_tokens > 0
        assert result.summary_tokens > 0
        assert result.compression_ratio > 0

    @pytest.mark.asyncio
    async def test_summarize_extracts_entities(self, summarizer):
        """Test that summarization extracts entities."""
        messages = [
            MockMessage(kind="user", content="SSH to @web-01 and check nginx"),
            MockMessage(kind="assistant", content="Connected to 192.168.1.10"),
        ]

        result = await summarizer.summarize(messages)

        assert "web-01" in result.key_entities or "192.168.1.10" in result.key_entities

    @pytest.mark.asyncio
    async def test_summarize_extracts_actions(self, summarizer):
        """Test that summarization extracts actions."""
        messages = [
            MockMessage(
                kind="assistant",
                content="Executed command, found 3 errors, restarted nginx",
            ),
        ]

        result = await summarizer.summarize(messages)

        # Should find action keywords
        assert len(result.key_actions) > 0 or "restarted" in result.summary.lower()

    def test_estimate_savings(self, summarizer):
        """Test savings estimate formatting."""
        from merlya.session.summarizer import SummaryResult

        result = SummaryResult(
            summary="test",
            original_tokens=1000,
            summary_tokens=200,
            compression_ratio=0.2,
            method="extractive",
        )

        savings = summarizer.estimate_savings(result)

        assert "1,000" in savings  # Original
        assert "200" in savings  # Summary
        assert "80" in savings  # Percentage saved


class TestTierConfig:
    """Tests for tier configuration."""

    def test_all_tiers_have_config(self):
        """Test that all tiers have configuration."""
        for tier in ContextTier:
            assert tier in TIER_CONFIG

    def test_tiers_are_ordered(self):
        """Test that tiers are ordered by capacity."""
        minimal = TIER_CONFIG[ContextTier.MINIMAL]
        standard = TIER_CONFIG[ContextTier.STANDARD]
        extended = TIER_CONFIG[ContextTier.EXTENDED]

        assert minimal.max_messages < standard.max_messages < extended.max_messages
        assert minimal.max_tokens < standard.max_tokens < extended.max_tokens

    def test_summarize_thresholds(self):
        """Test summarize thresholds are valid."""
        for config in TIER_CONFIG.values():
            assert 0 < config.summarize_threshold <= 1.0


class TestComplexityFactors:
    """Tests for ComplexityFactors."""

    def test_to_dict(self):
        """Test converting factors to dict."""
        factors = ComplexityFactors(
            message_length=100,
            line_count=5,
            word_count=20,
            has_logs=True,
            has_code=False,
            has_json=False,
            has_paths=True,
            has_multiple_hosts=False,
            router_confidence=0.8,
            is_incident=True,
            is_remediation=False,
            entities_count=3,
            has_jump_host=False,
            question_count=1,
            command_count=2,
        )

        d = factors.to_dict()

        assert d["message_length"] == 100
        assert d["has_logs"] is True
        assert d["router_confidence"] == 0.8
        assert len(d) == 15  # All fields present


class TestSessionManagerValidation:
    """Tests for SessionManager validation (N7: coverage gaps)."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        return SessionManager(db=None, model="gpt-4")

    @pytest.mark.asyncio
    async def test_load_session_invalid_uuid(self, manager):
        """Test that invalid UUID raises ValueError."""
        from merlya.session.manager import SessionManager

        manager = SessionManager(db=None)

        # Invalid UUID should raise ValueError
        with pytest.raises(ValueError, match="Invalid session ID format"):
            await manager.load_session("not-a-valid-uuid")

        with pytest.raises(ValueError, match="Invalid session ID format"):
            await manager.load_session("12345")

    @pytest.mark.asyncio
    async def test_load_session_valid_uuid_no_db(self, manager):
        """Test that valid UUID with no DB returns None."""
        result = await manager.load_session("12345678-1234-1234-1234-123456789012")
        assert result is None

    @pytest.mark.asyncio
    async def test_start_session_creates_state(self, manager):
        """Test that start_session creates a valid session state."""
        session = await manager.start_session()

        assert session is not None
        assert session.id is not None
        assert len(session.id) == 36  # UUID format
        assert session.token_count == 0
        assert session.message_count == 0


class TestSafeCompressionRatio:
    """Tests for safe compression ratio calculation (N5)."""

    def test_compression_ratio_normal(self):
        """Test normal compression ratio calculation."""
        from merlya.session.summarizer import _safe_compression_ratio

        ratio = _safe_compression_ratio(100, 1000)
        assert ratio == 0.1

    def test_compression_ratio_zero_original(self):
        """Test compression ratio with zero original tokens."""
        from merlya.session.summarizer import _safe_compression_ratio

        ratio = _safe_compression_ratio(100, 0)
        assert ratio == 1.0

    def test_compression_ratio_negative_original(self):
        """Test compression ratio with negative original tokens."""
        from merlya.session.summarizer import _safe_compression_ratio

        ratio = _safe_compression_ratio(100, -10)
        assert ratio == 1.0


class TestTokenEstimatorConstants:
    """Tests for token estimator constants (N3)."""

    def test_constants_imported(self):
        """Test that constants are accessible."""
        from merlya.session.token_estimator import (
            CODE_CHARS_PER_TOKEN,
            COMPLETION_RATIO,
            DEFAULT_CHARS_PER_TOKEN,
            DEFAULT_CONTEXT_LIMIT,
            JSON_CHARS_PER_TOKEN,
            MAX_COMPLETION_ESTIMATE,
            MESSAGE_OVERHEAD_TOKENS,
        )

        assert DEFAULT_CHARS_PER_TOKEN == 4.0
        assert CODE_CHARS_PER_TOKEN == 3.0
        assert JSON_CHARS_PER_TOKEN == 2.5
        assert MESSAGE_OVERHEAD_TOKENS == 4
        assert COMPLETION_RATIO == 0.25
        assert MAX_COMPLETION_ESTIMATE == 2000
        assert DEFAULT_CONTEXT_LIMIT == 8192


# ==============================================================================
# Extended Tests for SessionManager
# ==============================================================================


class TestSessionManagerExtended:
    """Extended tests for SessionManager."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        return SessionManager(db=None, model="gpt-4")

    def test_get_instance_singleton(self, manager):
        """Test get_instance returns singleton."""
        from merlya.session.manager import SessionManager

        instance = SessionManager.get_instance()
        assert instance is manager

    def test_reset_instance(self):
        """Test reset_instance clears singleton."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        assert SessionManager.get_instance() is None

    def test_current_tier_no_session(self, manager):
        """Test current_tier when no session started."""
        assert manager.current_tier == ContextTier.STANDARD

    def test_tier_property(self, manager):
        """Test tier property."""
        assert manager.tier == ContextTier.STANDARD

    def test_limits_property(self, manager):
        """Test limits property."""
        limits = manager.limits
        assert limits.max_messages > 0
        assert limits.max_tokens > 0

    @pytest.mark.asyncio
    async def test_start_session_with_conversation_id(self, manager):
        """Test starting session with conversation ID."""
        conv_id = "test-conversation-123"
        session = await manager.start_session(conversation_id=conv_id)

        assert session.conversation_id == conv_id

    @pytest.mark.asyncio
    async def test_start_session_with_tier(self, manager):
        """Test starting session with specific tier."""
        session = await manager.start_session(tier=ContextTier.EXTENDED)

        assert session.tier == ContextTier.EXTENDED

    @pytest.mark.asyncio
    async def test_session_property(self, manager):
        """Test session property."""
        assert manager.session is None

        await manager.start_session()
        assert manager.session is not None

    @pytest.mark.asyncio
    async def test_add_message_starts_session(self, manager):
        """Test that add_message starts session if needed."""
        assert manager.session is None

        await manager.add_message(MockMessage(kind="user", content="test"))

        assert manager.session is not None
        assert manager.session.message_count == 1


class TestSessionManagerAddMessage:
    """Tests for add_message functionality."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        return SessionManager(db=None, model="gpt-4")

    @pytest.mark.asyncio
    async def test_add_message_increments_counts(self, manager):
        """Test that add_message increments counters."""
        await manager.start_session()
        initial_count = manager.session.message_count

        await manager.add_message(MockMessage(kind="user", content="hello world"))

        assert manager.session.message_count == initial_count + 1
        assert manager.session.token_count > 0

    @pytest.mark.asyncio
    async def test_add_multiple_messages(self, manager):
        """Test adding multiple messages."""
        await manager.start_session()

        for i in range(5):
            await manager.add_message(MockMessage(kind="user", content=f"message {i}"))

        assert manager.session.message_count == 5


class TestSessionManagerExtractContent:
    """Tests for _extract_content method."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        return SessionManager(db=None, model="gpt-4")

    def test_extract_content_string(self, manager):
        """Test extracting string content."""

        @dataclass
        class StringMessage:
            content: str

        msg = StringMessage(content="hello world")
        content = manager._extract_content(msg)
        assert content == "hello world"

    def test_extract_content_list_of_strings(self, manager):
        """Test extracting content from list of strings."""

        @dataclass
        class ListMessage:
            content: list

        msg = ListMessage(content=["hello", "world"])
        content = manager._extract_content(msg)
        assert "hello" in content
        assert "world" in content

    def test_extract_content_list_of_objects_with_text(self, manager):
        """Test extracting content from list of objects with text attribute."""

        @dataclass
        class TextPart:
            text: str

        @dataclass
        class ListMessage:
            content: list

        msg = ListMessage(content=[TextPart(text="hello"), TextPart(text="world")])
        content = manager._extract_content(msg)
        assert "hello" in content
        assert "world" in content

    def test_extract_content_fallback(self, manager):
        """Test fallback to str() for unknown types."""

        class UnknownMessage:
            pass

        msg = UnknownMessage()
        content = manager._extract_content(msg)
        assert "UnknownMessage" in content


class TestSessionManagerShouldSummarize:
    """Tests for _should_summarize method."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        return SessionManager(db=None, model="gpt-4")

    def test_should_summarize_no_session(self, manager):
        """Test _should_summarize with no session."""
        assert manager._should_summarize() is False

    @pytest.mark.asyncio
    async def test_should_summarize_below_threshold(self, manager):
        """Test _should_summarize below threshold."""
        await manager.start_session()
        manager.session.message_count = 5
        manager.session.token_count = 500

        assert manager._should_summarize() is False

    @pytest.mark.asyncio
    async def test_should_summarize_above_messages_threshold(self, manager):
        """Test _should_summarize above messages threshold."""
        await manager.start_session(tier=ContextTier.MINIMAL)
        limits = TIER_CONFIG[ContextTier.MINIMAL]

        manager.session.message_count = int(limits.max_messages * 0.9)
        manager.session.token_count = 100

        assert manager._should_summarize() is True

    @pytest.mark.asyncio
    async def test_should_summarize_above_tokens_threshold(self, manager):
        """Test _should_summarize above tokens threshold."""
        await manager.start_session(tier=ContextTier.MINIMAL)
        limits = TIER_CONFIG[ContextTier.MINIMAL]

        manager.session.message_count = 5
        manager.session.token_count = int(limits.max_tokens * 0.9)

        assert manager._should_summarize() is True


class TestSessionStateToDict:
    """Tests for SessionState.to_dict()."""

    def test_session_state_to_dict(self):
        """Test SessionState.to_dict()."""
        from merlya.session.manager import SessionState

        session = SessionState(
            id="test-id",
            conversation_id="conv-123",
            tier=ContextTier.STANDARD,
            summary="test summary",
            token_count=100,
            message_count=5,
        )

        d = session.to_dict()

        assert d["id"] == "test-id"
        assert d["conversation_id"] == "conv-123"
        assert d["tier"] == "standard"
        assert d["summary"] == "test summary"
        assert d["token_count"] == 100
        assert d["message_count"] == 5


class TestSessionManagerGetContextWindow:
    """Tests for get_context_window method."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        return SessionManager(db=None, model="gpt-4")

    @pytest.mark.asyncio
    async def test_get_context_window_starts_session(self, manager):
        """Test that get_context_window starts session if needed."""
        window = await manager.get_context_window()

        assert window is not None
        assert manager.session is not None

    @pytest.mark.asyncio
    async def test_get_context_window_returns_valid(self, manager):
        """Test get_context_window returns valid window."""
        await manager.start_session()
        await manager.add_message(MockMessage(kind="user", content="test message"))

        window = await manager.get_context_window()

        assert window.messages is not None
        assert window.tier is not None
        assert window.limits is not None


class TestSessionManagerEndSession:
    """Tests for end_session method."""

    @pytest.fixture
    def manager(self):
        """Create a session manager."""
        from merlya.session.manager import SessionManager

        SessionManager.reset_instance()
        return SessionManager(db=None, model="gpt-4")

    @pytest.mark.asyncio
    async def test_end_session_clears_state(self, manager):
        """Test that end_session clears session state."""
        await manager.start_session()
        assert manager.session is not None

        await manager.end_session()
        assert manager.session is None

    @pytest.mark.asyncio
    async def test_end_session_when_no_session(self, manager):
        """Test end_session when no session exists."""
        await manager.end_session()  # Should not raise
        assert manager.session is None
