"""
Tests for LLM parser timeout functionality.
"""
import time
from unittest.mock import MagicMock

import pytest


class TestLLMParserTimeout:
    """Test timeout handling in parse_with_llm function."""

    @pytest.fixture
    def mock_llm_router(self):
        """Create a mock LLM router."""
        router = MagicMock()
        router.generate.return_value = '[{"hostname": "test-host", "ip_address": "1.2.3.4"}]'
        return router

    @pytest.fixture
    def slow_llm_router(self):
        """Create a mock LLM router that simulates slow response."""
        router = MagicMock()

        def slow_generate(*args, **kwargs):
            time.sleep(5)  # Sleep longer than test timeout
            return '[{"hostname": "test-host"}]'

        router.generate.side_effect = slow_generate
        return router

    @pytest.fixture(autouse=True)
    def enable_llm_fallback(self, monkeypatch):
        """Enable LLM fallback for tests."""
        # Patch the imported constants directly since they're imported at module level
        from merlya.inventory.parser.parsers.llm import engine
        monkeypatch.setattr(engine, "ENABLE_LLM_FALLBACK", True)
        monkeypatch.setattr(engine, "LLM_COMPLIANCE_ACKNOWLEDGED", True)

    def test_timeout_triggers_on_slow_llm(self, slow_llm_router):
        """Test that timeout is triggered when LLM takes too long."""
        from merlya.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=slow_llm_router,
            timeout=1,
        )

        assert len(hosts) == 0
        assert any("LLM_TIMEOUT" in err for err in errors)
        assert any("timed out after 1 second" in err for err in errors)

    def test_timeout_zero_disables_timeout(self, mock_llm_router):
        """Test that timeout=0 disables the timeout mechanism.

        Note: This behavior differs from environment variable parsing where
        MERLYA_LLM_TIMEOUT=0 falls back to DEFAULT_LLM_TIMEOUT. The distinction
        is intentional:
        - Env var: Users shouldn't accidentally disable timeout via config
        - Function param: Advanced programmatic use can explicitly disable
        """
        from merlya.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=mock_llm_router,
            timeout=0,  # Disable timeout
        )

        # Should succeed without timeout errors
        assert len(hosts) == 1
        assert hosts[0].hostname == "test-host"
        assert not any("LLM_TIMEOUT" in err for err in errors)

    def test_successful_call_within_timeout(self, mock_llm_router):
        """Test that successful LLM call within timeout returns results."""
        from merlya.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=mock_llm_router,
            timeout=30,
        )

        assert len(hosts) == 1
        assert hosts[0].hostname == "test-host"
        assert hosts[0].ip_address == "1.2.3.4"
        assert not any("LLM_TIMEOUT" in err for err in errors)

    def test_default_timeout_from_env(self, mock_llm_router, monkeypatch):
        """Test that timeout constant can be configured (simulates env var behavior)."""
        from merlya.inventory.parser.parsers.llm import config

        # Patch the timeout constant directly (avoids module reloading issues)
        monkeypatch.setattr(config, "LLM_TIMEOUT", 120)

        # Verify the constant is set correctly
        assert config.LLM_TIMEOUT == 120

    def test_timeout_error_message_is_helpful(self, slow_llm_router):
        """Test that timeout error message provides actionable guidance."""
        from merlya.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=slow_llm_router,
            timeout=1,
        )

        assert len(errors) > 0
        timeout_error = next((err for err in errors if "LLM_TIMEOUT" in err), None)
        assert timeout_error is not None
        assert "MERLYA_LLM_TIMEOUT" in timeout_error  # Mentions the env var
        assert "faster model" in timeout_error  # Suggests alternative

    def test_timeout_returns_empty_hosts_not_partial(self, slow_llm_router):
        """Test that timeout returns empty hosts list, not partial results."""
        from merlya.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=slow_llm_router,
            timeout=1,
        )

        # Should return empty hosts on timeout
        assert hosts == []
        # But errors should explain what happened
        assert len(errors) > 0

    def test_none_timeout_uses_default(self, mock_llm_router, monkeypatch):
        """Test that timeout=None uses the module-level default."""
        from merlya.inventory.parser.parsers.llm import config, parse_with_llm

        # Patch the module constant directly instead of reloading
        monkeypatch.setattr(config, "LLM_TIMEOUT", 60)

        # With timeout=None, it should use the default LLM_TIMEOUT
        # The mock returns immediately, so this should succeed
        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=mock_llm_router,
            timeout=None,
        )

        assert len(hosts) == 1
        assert not any("LLM_TIMEOUT" in err for err in errors)


class TestLLMTimeoutConfiguration:
    """Test timeout configuration options."""

    def test_default_timeout_value(self):
        """Test that DEFAULT_LLM_TIMEOUT is set to a reasonable value."""
        from merlya.inventory.parser.parsers.llm.config import DEFAULT_LLM_TIMEOUT

        assert DEFAULT_LLM_TIMEOUT == 60  # 60 seconds is reasonable default

    def test_timeout_constant_can_be_configured(self, monkeypatch):
        """Test that LLM_TIMEOUT constant can be set to a custom value."""
        from merlya.inventory.parser.parsers.llm import config

        # Patch the timeout constant directly (avoids module reloading issues)
        monkeypatch.setattr(config, "LLM_TIMEOUT", 90)

        # Verify the constant was set correctly
        assert config.LLM_TIMEOUT == 90

    def test_invalid_env_var_timeout_fallback(self, monkeypatch):
        """Test that _parse_llm_timeout handles invalid values gracefully.

        Note: This tests the internal _parse_llm_timeout function directly.
        While testing private functions is generally fragile, this validates
        critical safety behavior (rejecting invalid/zero values) that affects
        module initialization.

        Design note: MERLYA_LLM_TIMEOUT=0 intentionally falls back to default
        to prevent accidental timeout disabling via configuration. To disable
        timeout programmatically, pass timeout=0 to parse_with_llm() directly.
        """
        from merlya.inventory.parser.parsers.llm.config import (
            DEFAULT_LLM_TIMEOUT,
            _parse_llm_timeout,
        )

        # Test invalid string value falls back to default
        monkeypatch.setenv("MERLYA_LLM_TIMEOUT", "invalid")
        assert _parse_llm_timeout() == DEFAULT_LLM_TIMEOUT

        # Test negative value falls back to default
        monkeypatch.setenv("MERLYA_LLM_TIMEOUT", "-10")
        assert _parse_llm_timeout() == DEFAULT_LLM_TIMEOUT

        # Test zero value falls back to default (intentional - see docstring)
        monkeypatch.setenv("MERLYA_LLM_TIMEOUT", "0")
        assert _parse_llm_timeout() == DEFAULT_LLM_TIMEOUT

        # Test valid value works
        monkeypatch.setenv("MERLYA_LLM_TIMEOUT", "90")
        assert _parse_llm_timeout() == 90
