"""
Tests for Orchestrator model selection bug fix.

Ensures that the orchestrator uses the correct model for each provider,
not the model configured for a different provider.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from athena_ai.agents.orchestrator import Orchestrator, OrchestratorMode


@pytest.fixture
def mock_model_config():
    """Mock ModelConfig that returns different models for different providers."""
    config = MagicMock()
    config.get_provider.return_value = "ollama"

    # Define different models for each provider
    def get_model_for_provider(provider, task=None):
        models = {
            "ollama": "mistral-small3.1:latest",
            "openrouter": "anthropic/claude-4.5-sonnet-20250929",
            "anthropic": "claude-3-5-sonnet-20241022",
            "openai": "gpt-4o"
        }
        return models.get(provider, "unknown")

    config.get_model.side_effect = get_model_for_provider
    return config


class TestOrchestratorModelSelection:
    """Tests for orchestrator model selection."""

    @patch.dict(os.environ, {
        "OPENROUTER_API_KEY": "test-key",
        "ATHENA_PROVIDER": "openrouter"  # ✅ Force provider to openrouter
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.OpenAIChatCompletionClient')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    def test_openrouter_uses_openrouter_model_not_ollama(
        self, mock_planner, mock_tools, mock_client, mock_config_class, mock_model_config
    ):
        """
        When using OpenRouter, should use OpenRouter model from config,
        NOT the Ollama model (regression test for bug).
        """
        mock_config_class.return_value = mock_model_config

        # Create orchestrator (will trigger _create_model_client)
        try:
            orchestrator = Orchestrator(mode=OrchestratorMode.BASIC)
        except Exception:
            # Initialization might fail due to missing dependencies, that's ok
            # We only care about the model client creation
            pass

        # Verify that OpenAIChatCompletionClient was called with correct model
        mock_client.assert_called_once()
        call_kwargs = mock_client.call_args.kwargs

        # Should use OpenRouter model, NOT Ollama model
        assert call_kwargs["model"] == "anthropic/claude-4.5-sonnet-20250929"
        assert call_kwargs["model"] != "mistral-small3.1:latest"
        assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"

    @patch.dict(os.environ, {
        "ANTHROPIC_API_KEY": "test-key",
        "ATHENA_PROVIDER": "anthropic"  # ✅ Force provider to anthropic
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.OpenAIChatCompletionClient')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    def test_anthropic_uses_anthropic_model_not_ollama(
        self, mock_planner, mock_tools, mock_client, mock_config_class, mock_model_config
    ):
        """When using Anthropic, should use Anthropic model, not Ollama model."""
        mock_config_class.return_value = mock_model_config

        try:
            orchestrator = Orchestrator(mode=OrchestratorMode.BASIC)
        except Exception:
            pass

        mock_client.assert_called_once()
        call_kwargs = mock_client.call_args.kwargs

        assert call_kwargs["model"] == "claude-3-5-sonnet-20241022"
        assert call_kwargs["model"] != "mistral-small3.1:latest"
        assert call_kwargs["base_url"] == "https://api.anthropic.com/v1"

    @patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "ATHENA_PROVIDER": "openai"  # ✅ Force provider to openai
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.OpenAIChatCompletionClient')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    def test_openai_uses_openai_model_not_ollama(
        self, mock_planner, mock_tools, mock_client, mock_config_class, mock_model_config
    ):
        """When using OpenAI, should use OpenAI model, not Ollama model."""
        mock_config_class.return_value = mock_model_config

        try:
            orchestrator = Orchestrator(mode=OrchestratorMode.BASIC)
        except Exception:
            pass

        mock_client.assert_called_once()
        call_kwargs = mock_client.call_args.kwargs

        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["model"] != "mistral-small3.1:latest"

    @patch.dict(os.environ, {"ATHENA_PROVIDER": "ollama"}, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.OpenAIChatCompletionClient')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_ollama_uses_ollama_model(
        self, mock_ollama_client, mock_planner, mock_tools, mock_client, mock_config_class, mock_model_config
    ):
        """When using Ollama (default provider), should use Ollama model."""
        mock_config_class.return_value = mock_model_config
        mock_ollama_instance = MagicMock()
        mock_ollama_instance.is_available.return_value = True
        mock_ollama_instance.get_model_names.return_value = ["mistral-small3.1:latest"]
        mock_ollama_client.return_value = mock_ollama_instance

        try:
            orchestrator = Orchestrator(mode=OrchestratorMode.BASIC)
        except Exception:
            pass

        mock_client.assert_called_once()
        call_kwargs = mock_client.call_args.kwargs

        assert call_kwargs["model"] == "mistral-small3.1:latest"
        assert call_kwargs["base_url"] == "http://localhost:11434/v1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
