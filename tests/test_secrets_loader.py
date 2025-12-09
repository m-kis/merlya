"""Tests for API key loading from keyring."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from merlya.secrets.loader import load_api_keys_from_keyring


@pytest.fixture
def mock_config():
    """Create mock config for OpenRouter provider."""
    config = MagicMock()
    config.model.provider = "openrouter"
    config.model.api_key_env = "OPENROUTER_API_KEY"
    return config


@pytest.fixture
def mock_secrets():
    """Create mock secret store."""
    secrets = MagicMock()
    secrets.get.return_value = "test-api-key"
    return secrets


@pytest.fixture(autouse=True)
def cleanup_env():
    """Clean up environment variables after each test."""
    original = os.environ.copy()
    yield
    # Restore original environment
    os.environ.clear()
    os.environ.update(original)


def test_loads_key_from_keyring(mock_config, mock_secrets):
    """Test that API key is loaded from keyring to env."""
    os.environ.pop("OPENROUTER_API_KEY", None)

    load_api_keys_from_keyring(mock_config, mock_secrets)

    assert os.environ.get("OPENROUTER_API_KEY") == "test-api-key"
    mock_secrets.get.assert_called_once_with("OPENROUTER_API_KEY")


def test_skips_if_already_in_env(mock_config, mock_secrets):
    """Test that existing env var is not overwritten."""
    os.environ["OPENROUTER_API_KEY"] = "existing-key"

    load_api_keys_from_keyring(mock_config, mock_secrets)

    assert os.environ.get("OPENROUTER_API_KEY") == "existing-key"
    mock_secrets.get.assert_not_called()


def test_uses_provider_fallback(mock_secrets):
    """Test fallback to provider-based env var name."""
    config = MagicMock()
    config.model.provider = "anthropic"
    config.model.api_key_env = None

    os.environ.pop("ANTHROPIC_API_KEY", None)

    load_api_keys_from_keyring(config, mock_secrets)

    mock_secrets.get.assert_called_once_with("ANTHROPIC_API_KEY")


def test_ollama_local_skips_api_key():
    """Test that Ollama local mode doesn't require API key."""
    config = MagicMock()
    config.model.provider = "ollama"
    config.model.api_key_env = None
    config.model.base_url = "http://localhost:11434"

    secrets = MagicMock()

    load_api_keys_from_keyring(config, secrets)

    # Should not attempt to load key for local Ollama
    secrets.get.assert_not_called()


def test_warns_when_key_not_found(mock_config, caplog):
    """Test warning when API key is not found."""
    secrets = MagicMock()
    secrets.get.return_value = None

    os.environ.pop("OPENROUTER_API_KEY", None)

    with caplog.at_level("WARNING"):
        load_api_keys_from_keyring(mock_config, secrets)

    assert "OPENROUTER_API_KEY" not in os.environ
