"""
Tests for Session Manager functionality.

Tests TokenEstimator, ContextTierPredictor, SessionSummarizer, SessionManager.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

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
