"""
Tests for Ollama model auto-download feature.

Tests the automatic download handling when setting Ollama models.
"""

from unittest.mock import MagicMock, patch

import pytest

from athena_ai.repl.commands.model import ModelCommandHandler


@pytest.fixture
def mock_repl():
    """Create a mock REPL instance."""
    repl = MagicMock()
    repl.orchestrator = MagicMock()
    repl.orchestrator.llm_router = MagicMock()
    repl.orchestrator.llm_router.model_config = MagicMock()
    return repl


@pytest.fixture
def model_handler(mock_repl):
    """Create a ModelCommandHandler with mock REPL."""
    return ModelCommandHandler(mock_repl)


class TestOllamaModelSetup:
    """Tests for Ollama model setup and auto-download."""

    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_server_unavailable(
        self, mock_get_client, model_handler
    ):
        """Should return False if Ollama server is not available."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        mock_client.base_url = "http://localhost:11434"
        mock_get_client.return_value = mock_client

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is False
        mock_client.is_available.assert_called_once()

    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_model_already_exists(
        self, mock_get_client, model_handler
    ):
        """Should return True if model is already downloaded."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.has_model.return_value = True
        mock_get_client.return_value = mock_client

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is True
        mock_client.has_model.assert_called_once_with("llama3")
        # Should not attempt to download
        mock_client.pull_model.assert_not_called()

    @patch('builtins.input')
    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_user_declines_download(
        self, mock_get_client, mock_input, model_handler
    ):
        """Should return False if user declines to download model."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.has_model.return_value = False
        mock_get_client.return_value = mock_client
        mock_input.return_value = "n"  # User says no

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is False
        mock_client.pull_model.assert_not_called()

    @patch('builtins.input')
    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_download_success(
        self, mock_get_client, mock_input, model_handler
    ):
        """Should download model and return True on success."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.has_model.return_value = False
        mock_client.pull_model.return_value = True
        mock_get_client.return_value = mock_client
        mock_input.return_value = "y"  # User says yes

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is True
        mock_client.pull_model.assert_called_once_with("llama3")

    @patch('builtins.input')
    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_download_failure(
        self, mock_get_client, mock_input, model_handler
    ):
        """Should return False if download fails."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.has_model.return_value = False
        mock_client.pull_model.return_value = False
        mock_get_client.return_value = mock_client
        mock_input.return_value = "y"

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is False
        mock_client.pull_model.assert_called_once_with("llama3")

    @patch('builtins.input')
    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_eoferror(
        self, mock_get_client, mock_input, model_handler
    ):
        """Should handle gracefully if input raises EOFError."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.has_model.return_value = False
        mock_get_client.return_value = mock_client
        mock_input.side_effect = EOFError()

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is False
        mock_client.pull_model.assert_not_called()

    @patch('builtins.input')
    @patch('athena_ai.llm.ollama_client.get_ollama_client')
    def test_handle_ollama_model_setup_user_interrupt(
        self, mock_get_client, mock_input, model_handler
    ):
        """Should handle gracefully if user interrupts with Ctrl+C."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.has_model.return_value = False
        mock_get_client.return_value = mock_client
        mock_input.side_effect = KeyboardInterrupt()

        result = model_handler._handle_ollama_model_setup("llama3")

        assert result is False
        mock_client.pull_model.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
