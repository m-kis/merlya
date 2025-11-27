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
        monkeypatch.setenv("ATHENA_ENABLE_LLM_FALLBACK", "true")
        monkeypatch.setenv("ATHENA_LLM_COMPLIANCE_ACKNOWLEDGED", "true")

    def test_timeout_triggers_on_slow_llm(self, slow_llm_router):
        """Test that timeout is triggered when LLM takes too long."""
        from athena_ai.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=slow_llm_router,
            timeout=1,
        )

        assert len(hosts) == 0
        assert any("LLM_TIMEOUT" in err for err in errors)
        assert any("timed out after 1 second" in err for err in errors)

    def test_explicit_timeout_parameter(self, slow_llm_router):
        """Test that explicit timeout parameter works."""
        from athena_ai.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=slow_llm_router,
            timeout=1,  # Override with 1 second
        )

        assert len(hosts) == 0
        assert any("LLM_TIMEOUT" in err for err in errors)

    def test_timeout_zero_disables_timeout(self, mock_llm_router):
        """Test that timeout=0 disables the timeout mechanism."""
        from athena_ai.inventory.parser.parsers.llm import parse_with_llm

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
        from athena_ai.inventory.parser.parsers.llm import parse_with_llm

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
        """Test that default timeout is read from environment variable."""
        monkeypatch.setenv("ATHENA_LLM_TIMEOUT", "120")

        from athena_ai.inventory.parser.parsers import llm
        import importlib
        importlib.reload(llm)

        assert llm.LLM_TIMEOUT == 120

    def test_timeout_error_message_is_helpful(self, slow_llm_router):
        """Test that timeout error message provides actionable guidance."""
        from athena_ai.inventory.parser.parsers.llm import parse_with_llm

        hosts, errors, warnings = parse_with_llm(
            content="test content",
            llm_router=slow_llm_router,
            timeout=1,
        )

        assert len(errors) > 0
        timeout_error = next((err for err in errors if "LLM_TIMEOUT" in err), None)
        assert timeout_error is not None
        assert "ATHENA_LLM_TIMEOUT" in timeout_error  # Mentions the env var
        assert "faster model" in timeout_error  # Suggests alternative

    def test_timeout_returns_empty_hosts_not_partial(self, slow_llm_router):
        """Test that timeout returns empty hosts list, not partial results."""
        from athena_ai.inventory.parser.parsers.llm import parse_with_llm

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
        monkeypatch.setenv("ATHENA_LLM_TIMEOUT", "60")

        from athena_ai.inventory.parser.parsers import llm
        import importlib
        importlib.reload(llm)

        # With timeout=None, it should use the default LLM_TIMEOUT
        # The mock returns immediately, so this should succeed
        hosts, errors, warnings = llm.parse_with_llm(
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
        from athena_ai.inventory.parser.parsers.llm import DEFAULT_LLM_TIMEOUT

        assert DEFAULT_LLM_TIMEOUT == 60  # 60 seconds is reasonable default

    def test_env_var_timeout_parsing(self, monkeypatch):
        """Test that ATHENA_LLM_TIMEOUT env var is properly parsed."""
        monkeypatch.setenv("ATHENA_LLM_TIMEOUT", "90")

        from athena_ai.inventory.parser.parsers import llm
        import importlib
        importlib.reload(llm)

        assert llm.LLM_TIMEOUT == 90

    def test_invalid_env_var_timeout_fallback(self, monkeypatch):
        """Test behavior with invalid ATHENA_LLM_TIMEOUT value."""
        # This should raise ValueError during module load
        monkeypatch.setenv("ATHENA_LLM_TIMEOUT", "invalid")

        from athena_ai.inventory.parser.parsers import llm
        import importlib

        with pytest.raises(ValueError):
            importlib.reload(llm)
