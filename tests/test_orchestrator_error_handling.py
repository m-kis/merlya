"""
Tests for Orchestrator error handling.

Ensures that errors are caught and presented with clear, actionable messages.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from athena_ai.agents.orchestrator import Orchestrator, OrchestratorMode


@pytest.fixture
def mock_model_config():
    """Mock ModelConfig that returns test configuration."""
    config = MagicMock()
    config.get_provider.return_value = "openrouter"
    config.get_model.return_value = "anthropic/claude-4.5-sonnet-20250929"
    return config


class TestOrchestratorErrorHandling:
    """Tests for orchestrator error handling."""

    @patch.dict(os.environ, {
        "OPENROUTER_API_KEY": "test-key",
        "ATHENA_PROVIDER": "openrouter"
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    @pytest.mark.asyncio
    async def test_function_calling_not_supported_error(
        self, mock_planner_class, mock_tools, mock_config_class, mock_model_config
    ):
        """
        Should return actionable error message when model doesn't support function calling.
        """
        mock_config_class.return_value = mock_model_config

        # Create a mock orchestrator with the real _handle_execution_error method
        from athena_ai.agents.orchestrator import Orchestrator
        orchestrator = MagicMock(spec=Orchestrator)

        # Bind the real _handle_execution_error and _build_function_calling_error_message methods
        orchestrator._handle_execution_error = Orchestrator._handle_execution_error.__get__(orchestrator)
        orchestrator._build_function_calling_error_message = Orchestrator._build_function_calling_error_message.__get__(orchestrator)

        # Mock process_request to use the real error handler
        async def mock_process_request(query):
            try:
                # Simulate the planner raising an error
                raise Exception("Error code: 404 - {'error': {'message': 'No endpoints found that support tool use'}}")
            except Exception as e:
                return orchestrator._handle_execution_error(e)

        orchestrator.process_request = mock_process_request

        # Call process_request
        result = await orchestrator.process_request("test query")

        # Verify error message is actionable
        assert "❌ Model Error" in result
        assert "doesn't support function calling" in result
        assert "💡 Solutions:" in result
        assert "/model set" in result or "/model provider" in result

    @patch.dict(os.environ, {
        "OPENROUTER_API_KEY": "test-key",
        "ATHENA_PROVIDER": "openrouter"
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    @pytest.mark.asyncio
    async def test_openrouter_error_suggests_compatible_models(
        self, mock_planner_class, mock_tools, mock_config_class, mock_model_config
    ):
        """
        Should suggest OpenRouter-specific compatible models when using OpenRouter.
        """
        mock_config_class.return_value = mock_model_config

        # Create a mock orchestrator with the real error handling methods
        from athena_ai.agents.orchestrator import Orchestrator
        orchestrator = MagicMock(spec=Orchestrator)
        orchestrator._handle_execution_error = Orchestrator._handle_execution_error.__get__(orchestrator)
        orchestrator._build_function_calling_error_message = Orchestrator._build_function_calling_error_message.__get__(orchestrator)

        async def mock_process_request(query):
            try:
                raise Exception("No endpoints found that support tool use")
            except Exception as e:
                return orchestrator._handle_execution_error(e)

        orchestrator.process_request = mock_process_request

        result = await orchestrator.process_request("test query")

        # Verify OpenRouter-specific suggestions
        assert "google/gemini-2.0-flash-exp:free" in result
        assert "anthropic/claude-3.5-sonnet" in result
        assert "qwen/qwen-2.5-72b-instruct" in result

    @patch.dict(os.environ, {
        "OPENROUTER_API_KEY": "test-key",
        "ATHENA_PROVIDER": "ollama"
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    @pytest.mark.asyncio
    async def test_ollama_error_suggests_cloud_fallback(
        self, mock_planner_class, mock_tools, mock_config_class
    ):
        """
        Should suggest cloud provider fallback when using Ollama.
        """
        # Mock config for Ollama
        ollama_config = MagicMock()
        ollama_config.get_provider.return_value = "ollama"
        ollama_config.get_model.return_value = "llama3:latest"
        mock_config_class.return_value = ollama_config

        # Create a mock orchestrator with the real error handling methods
        from athena_ai.agents.orchestrator import Orchestrator
        orchestrator = MagicMock(spec=Orchestrator)
        orchestrator._handle_execution_error = Orchestrator._handle_execution_error.__get__(orchestrator)
        orchestrator._build_function_calling_error_message = Orchestrator._build_function_calling_error_message.__get__(orchestrator)

        async def mock_process_request(query):
            try:
                raise Exception("404 - No endpoints found that support tool use")
            except Exception as e:
                return orchestrator._handle_execution_error(e)

        orchestrator.process_request = mock_process_request

        result = await orchestrator.process_request("test query")

        # Verify Ollama-specific suggestions
        assert "/model provider openrouter" in result
        assert "qwen2.5-coder:latest" in result

    @patch.dict(os.environ, {
        "OPENROUTER_API_KEY": "test-key",
        "ATHENA_PROVIDER": "openrouter"
    }, clear=True)
    @patch('athena_ai.agents.orchestrator.ModelConfig')
    @patch('athena_ai.agents.orchestrator.autogen_tools')
    @patch('athena_ai.agents.orchestrator.ExecutionPlanner')
    @pytest.mark.asyncio
    async def test_generic_error_still_shown(
        self, mock_planner_class, mock_tools, mock_config_class, mock_model_config
    ):
        """
        Should still show generic errors that are not function calling related.
        """
        mock_config_class.return_value = mock_model_config

        # Create a mock orchestrator with the real error handling methods
        from athena_ai.agents.orchestrator import Orchestrator
        orchestrator = MagicMock(spec=Orchestrator)
        orchestrator._handle_execution_error = Orchestrator._handle_execution_error.__get__(orchestrator)
        orchestrator._build_function_calling_error_message = Orchestrator._build_function_calling_error_message.__get__(orchestrator)

        async def mock_process_request(query):
            try:
                raise Exception("Some other error")
            except Exception as e:
                return orchestrator._handle_execution_error(e)

        orchestrator.process_request = mock_process_request

        result = await orchestrator.process_request("test query")

        # Verify generic error is shown
        assert "❌ Error:" in result
        assert "Some other error" in result
        # Should NOT show function calling help
        assert "doesn't support function calling" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
