"""
Tests for LLM provider readiness checks.

Ensures that:
1. Readiness checker correctly validates provider configuration
2. Ollama checks work (server + model)
3. Cloud provider checks work (API key)
4. Error handling is robust
"""
import os
from unittest.mock import MagicMock, patch

import pytest


class TestReadinessResult:
    """Test ReadinessResult dataclass."""

    def test_has_issues_with_errors(self):
        """Should report issues when errors present."""
        from merlya.llm.readiness import ReadinessResult

        result = ReadinessResult(provider="test", ready=False, errors=["Error 1"])
        assert result.has_issues is True

    def test_has_issues_with_warnings(self):
        """Should report issues when warnings present."""
        from merlya.llm.readiness import ReadinessResult

        result = ReadinessResult(provider="test", ready=True, warnings=["Warning 1"])
        assert result.has_issues is True

    def test_no_issues_when_clean(self):
        """Should report no issues when clean."""
        from merlya.llm.readiness import ReadinessResult

        result = ReadinessResult(provider="test", ready=True)
        assert result.has_issues is False


class TestProviderReadinessChecker:
    """Test ProviderReadinessChecker class."""

    @pytest.fixture
    def mock_model_config(self):
        """Create a mock ModelConfig."""
        mock = MagicMock()
        mock.get_provider.return_value = "openrouter"
        mock.get_model.return_value = "anthropic/claude-3.5-sonnet"
        return mock

    def test_check_uses_configured_provider(self, mock_model_config):
        """Should use provider from config if not specified."""
        from merlya.llm.readiness import ProviderReadinessChecker

        checker = ProviderReadinessChecker(model_config=mock_model_config)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            result = checker.check()

        assert result.provider == "openrouter"
        mock_model_config.get_provider.assert_called_once()

    def test_check_accepts_provider_override(self, mock_model_config):
        """Should use provider override if specified."""
        from merlya.llm.readiness import ProviderReadinessChecker

        mock_model_config.get_model.return_value = "gpt-4o"
        checker = ProviderReadinessChecker(model_config=mock_model_config)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            result = checker.check(provider="openai")

        assert result.provider == "openai"


class TestOllamaReadiness:
    """Test Ollama-specific readiness checks."""

    @pytest.fixture
    def checker(self):
        """Create checker with Ollama config."""
        from merlya.llm.readiness import ProviderReadinessChecker

        mock_config = MagicMock()
        mock_config.get_provider.return_value = "ollama"
        mock_config.get_model.return_value = "llama3"
        return ProviderReadinessChecker(model_config=mock_config)

    def test_ollama_server_not_available(self, checker):
        """Should fail when Ollama server is not running."""
        with patch("merlya.llm.ollama_client.OllamaClient") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.is_available.return_value = False

            result = checker.check()

        assert result.ready is False
        assert any("not available" in err for err in result.errors)

    def test_ollama_model_not_found(self, checker):
        """Should fail when configured model is not available."""
        with patch("merlya.llm.ollama_client.OllamaClient") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.is_available.return_value = True
            mock_instance.get_version.return_value = "0.3.0"
            mock_instance.has_model.return_value = False
            mock_instance.get_model_names.return_value = ["mistral", "qwen2"]

            result = checker.check()

        assert result.ready is False
        assert any("not found" in err for err in result.errors)
        assert any("mistral" in err or "qwen2" in err for err in result.errors)

    def test_ollama_ready_when_all_good(self, checker):
        """Should be ready when server and model are available."""
        with patch("merlya.llm.ollama_client.OllamaClient") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.is_available.return_value = True
            mock_instance.get_version.return_value = "0.3.0"
            mock_instance.has_model.return_value = True

            result = checker.check()

        assert result.ready is True
        assert len(result.errors) == 0


class TestOpenRouterReadiness:
    """Test OpenRouter-specific readiness checks."""

    @pytest.fixture
    def checker(self):
        """Create checker with OpenRouter config."""
        from merlya.llm.readiness import ProviderReadinessChecker

        mock_config = MagicMock()
        mock_config.get_provider.return_value = "openrouter"
        mock_config.get_model.return_value = "anthropic/claude-3.5-sonnet"
        return ProviderReadinessChecker(model_config=mock_config)

    def test_missing_api_key(self, checker):
        """Should fail when API key is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure OPENROUTER_API_KEY is not set
            os.environ.pop("OPENROUTER_API_KEY", None)
            result = checker.check()

        assert result.ready is False
        assert any("OPENROUTER_API_KEY" in err for err in result.errors)

    def test_ready_with_api_key(self, checker):
        """Should be ready when API key is set."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key-123"}):
            with patch("merlya.llm.readiness.requests.get") as mock_get:
                mock_get.return_value.status_code = 200
                result = checker.check()

        assert result.ready is True
        assert result.details.get("api_key") == "configured"

    def test_invalid_api_key(self, checker):
        """Should fail when API key is invalid."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "invalid-key"}):
            with patch("merlya.llm.readiness.requests.get") as mock_get:
                mock_get.return_value.status_code = 401
                result = checker.check()

        assert result.ready is False
        assert any("invalid" in err.lower() for err in result.errors)


class TestAnthropicReadiness:
    """Test Anthropic-specific readiness checks."""

    @pytest.fixture
    def checker(self):
        """Create checker with Anthropic config."""
        from merlya.llm.readiness import ProviderReadinessChecker

        mock_config = MagicMock()
        mock_config.get_provider.return_value = "anthropic"
        mock_config.get_model.return_value = "claude-3-5-sonnet-20241022"
        return ProviderReadinessChecker(model_config=mock_config)

    def test_missing_api_key(self, checker):
        """Should fail when API key is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = checker.check()

        assert result.ready is False
        assert any("ANTHROPIC_API_KEY" in err for err in result.errors)

    def test_ready_with_api_key(self, checker):
        """Should be ready when API key is set."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test123"}):
            result = checker.check()

        assert result.ready is True
        assert result.details.get("api_key") == "configured"


class TestOpenAIReadiness:
    """Test OpenAI-specific readiness checks."""

    @pytest.fixture
    def checker(self):
        """Create checker with OpenAI config."""
        from merlya.llm.readiness import ProviderReadinessChecker

        mock_config = MagicMock()
        mock_config.get_provider.return_value = "openai"
        mock_config.get_model.return_value = "gpt-4o"
        return ProviderReadinessChecker(model_config=mock_config)

    def test_missing_api_key(self, checker):
        """Should fail when API key is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            result = checker.check()

        assert result.ready is False
        assert any("OPENAI_API_KEY" in err for err in result.errors)

    def test_ready_with_api_key(self, checker):
        """Should be ready when API key is set."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}):
            result = checker.check()

        assert result.ready is True


class TestFormatReadinessResult:
    """Test format_readiness_result function."""

    def test_format_ready_result(self):
        """Should format ready result correctly."""
        from merlya.llm.readiness import ReadinessResult, format_readiness_result

        result = ReadinessResult(
            provider="openrouter",
            ready=True,
            model="claude-3.5-sonnet",
            details={"api_key": "configured"}
        )
        formatted = format_readiness_result(result)

        assert "OPENROUTER" in formatted
        assert "claude-3.5-sonnet" in formatted
        assert "api_key: configured" in formatted

    def test_format_error_result(self):
        """Should format error result correctly."""
        from merlya.llm.readiness import ReadinessResult, format_readiness_result

        result = ReadinessResult(
            provider="ollama",
            ready=False,
            errors=["Server not running"]
        )
        formatted = format_readiness_result(result)

        assert "OLLAMA" in formatted
        assert "Server not running" in formatted


class TestConvenienceFunction:
    """Test check_provider_readiness convenience function."""

    def test_check_provider_readiness(self):
        """Should create checker and run check."""
        from merlya.llm.readiness import check_provider_readiness

        with patch("merlya.llm.readiness.ModelConfig") as MockConfig:
            MockConfig.return_value.get_provider.return_value = "openai"
            MockConfig.return_value.get_model.return_value = "gpt-4o"

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                result = check_provider_readiness()

        assert result.provider == "openai"
