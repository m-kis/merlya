"""
Tests for recent improvements:
- Session-based logging
- Enhanced credentials parsing
- Interactive model configuration
- Task-specific routing
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from athena_ai.llm.model_config import ModelConfig
from athena_ai.security.credentials import CredentialManager, VariableType


class TestSessionLogging:
    """Test session-based logging functionality."""

    def test_session_id_format(self):
        """Test that session ID has correct format (YYYYMMDD_HHMMSS_mmm)."""
        import datetime
        session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]

        assert len(session_id) == 19
        assert session_id[8] == "_"
        assert session_id[15] == "_"
        assert session_id[:8].isdigit()  # Date part
        assert session_id[9:15].isdigit()  # Time part
        assert session_id[16:19].isdigit()  # Milliseconds part

    def test_session_id_uniqueness(self):
        """Test that consecutive session IDs are different."""
        import datetime
        import time

        session_id_1 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        time.sleep(0.001)  # Wait 1ms to ensure different timestamp
        session_id_2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]

        assert session_id_1 != session_id_2


class TestCredentialsParsing:
    """Test enhanced credentials parsing."""

    @pytest.fixture
    def cred_manager(self):
        """Create fresh CredentialManager for each test."""
        cm = CredentialManager()
        yield cm
        cm.clear_variables()

    def test_json_value_parsing(self, cred_manager):
        """Test parsing JSON values without quotes."""
        json_value = '{"env":"prod","region":"eu-west-1"}'
        cred_manager.set_variable("API_CONFIG", json_value, VariableType.CONFIG)

        result = cred_manager.get_variable("API_CONFIG")
        assert result == json_value
        # Verify it's valid JSON
        assert json.loads(result) == {"env": "prod", "region": "eu-west-1"}

    def test_url_value_parsing(self, cred_manager):
        """Test parsing URLs with parameters."""
        url_value = "https://api.example.com?token=abc123&callback=true"
        cred_manager.set_variable("WEBHOOK", url_value, VariableType.CONFIG)

        result = cred_manager.get_variable("WEBHOOK")
        assert result == url_value
        assert "token=abc123" in result
        assert "callback=true" in result

    def test_hash_value_parsing(self, cred_manager):
        """Test parsing hashes with special characters."""
        hash_value = "abc-123-{special}-456-[brackets]"
        cred_manager.set_variable("SECRET_HASH", hash_value, VariableType.CONFIG)

        result = cred_manager.get_variable("SECRET_HASH")
        assert result == hash_value
        assert "{special}" in result
        assert "[brackets]" in result

    def test_sql_query_parsing(self, cred_manager):
        """Test parsing SQL queries."""
        sql_value = "SELECT * FROM users WHERE active=1 AND role='admin'"
        cred_manager.set_variable("QUERY", sql_value, VariableType.CONFIG)

        result = cred_manager.get_variable("QUERY")
        assert result == sql_value
        assert "WHERE" in result
        assert "role='admin'" in result

    def test_ssh_key_parsing(self, cred_manager):
        """Test parsing SSH keys."""
        ssh_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC... user@host"
        cred_manager.set_variable("SSH_KEY", ssh_key, VariableType.CONFIG)

        result = cred_manager.get_variable("SSH_KEY")
        assert result == ssh_key
        assert "ssh-rsa" in result
        assert "user@host" in result

    def test_multiline_value_parsing(self, cred_manager):
        """Test parsing multiline values."""
        multiline = "line1\nline2\nline3"
        cred_manager.set_variable("MULTILINE", multiline, VariableType.CONFIG)

        result = cred_manager.get_variable("MULTILINE")
        assert result == multiline
        assert result.count("\n") == 2


class TestModelConfiguration:
    """Test interactive model configuration."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def model_config(self, temp_config_dir, monkeypatch):
        """Create ModelConfig with temporary directory."""
        monkeypatch.setattr("athena_ai.llm.model_config.Path.home", lambda: temp_config_dir)
        config = ModelConfig(auto_configure=False)
        yield config

    def test_default_config_creation(self, model_config):
        """Test default configuration is created correctly."""
        assert model_config.config["provider"] == "openrouter"
        assert "openrouter" in model_config.config["models"]
        assert "task_models" in model_config.config

    def test_set_provider(self, model_config):
        """Test setting provider."""
        model_config.set_provider("anthropic")
        assert model_config.get_provider() == "anthropic"

        # Test invalid provider
        with pytest.raises(ValueError):
            model_config.set_provider("invalid_provider")

    def test_set_model(self, model_config):
        """Test setting model for provider."""
        model_config.set_model("openrouter", "anthropic/claude-3.5-sonnet")
        model = model_config.get_model("openrouter")
        assert model == "anthropic/claude-3.5-sonnet"

    def test_task_model_configuration(self, model_config):
        """Test task-specific model configuration."""
        # Set task models
        model_config.set_task_model("correction", "haiku")
        model_config.set_task_model("planning", "opus")
        model_config.set_task_model("synthesis", "sonnet")

        # Get task models
        task_models = model_config.get_task_models()
        assert task_models["correction"] == "haiku"
        assert task_models["planning"] == "opus"
        assert task_models["synthesis"] == "sonnet"

    def test_task_model_with_full_path(self, model_config):
        """Test task model with full model path."""
        full_path = "meta-llama/llama-3.1-70b-instruct"
        model_config.set_task_model("synthesis", full_path)

        # Should use full path directly
        model = model_config.get_model(task="synthesis")
        assert full_path in model or model == full_path

    def test_invalid_task_raises_error(self, model_config):
        """Test setting invalid task raises ValueError."""
        with pytest.raises(ValueError):
            model_config.set_task_model("invalid_task", "haiku")

    def test_alias_resolution_openrouter(self, model_config):
        """Test alias resolution for OpenRouter."""
        model_config.set_provider("openrouter")

        # Test haiku alias
        haiku_model = model_config._resolve_model_alias("openrouter", "haiku")
        assert "haiku" in haiku_model.lower()

        # Test sonnet alias
        sonnet_model = model_config._resolve_model_alias("openrouter", "sonnet")
        assert "sonnet" in sonnet_model.lower()

        # Test opus alias
        opus_model = model_config._resolve_model_alias("openrouter", "opus")
        assert "opus" in opus_model.lower()

    def test_config_persistence(self, model_config, temp_config_dir):
        """Test configuration is saved and loaded correctly."""
        # Set configuration
        model_config.set_provider("ollama")
        model_config.set_model("ollama", "llama3.2")
        model_config.set_task_model("correction", "haiku")

        # Create new ModelConfig instance (should load from file)
        with patch("athena_ai.llm.model_config.Path.home", return_value=temp_config_dir):
            new_config = ModelConfig(auto_configure=False)

            assert new_config.get_provider() == "ollama"
            assert new_config.get_model("ollama") == "llama3.2"
            assert new_config.get_task_models()["correction"] == "haiku"

    def test_list_models(self, model_config):
        """Test listing available models."""
        models = model_config.list_models("openrouter")
        assert len(models) > 0
        assert any("claude" in m.lower() for m in models)

    def test_get_current_config(self, model_config):
        """Test getting current configuration."""
        config = model_config.get_current_config()
        assert "provider" in config
        assert "model" in config
        assert "task_models" in config


class TestTaskSpecificRouting:
    """Test task-specific routing functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def model_config(self, temp_config_dir, monkeypatch):
        """Create ModelConfig with temporary directory."""
        monkeypatch.setattr("athena_ai.llm.model_config.Path.home", lambda: temp_config_dir)
        config = ModelConfig(auto_configure=False)
        # Configure task-specific models
        config.set_task_model("correction", "haiku")
        config.set_task_model("planning", "opus")
        config.set_task_model("synthesis", "sonnet")
        yield config

    def test_correction_task_uses_haiku(self, model_config):
        """Test correction task uses haiku (fast model)."""
        model = model_config.get_model(task="correction")
        # Should resolve to haiku-based model
        assert "haiku" in model.lower() or model == "haiku"

    def test_planning_task_uses_opus(self, model_config):
        """Test planning task uses opus (powerful model)."""
        model = model_config.get_model(task="planning")
        # Should resolve to opus-based model
        assert "opus" in model.lower() or model == "opus"

    def test_synthesis_task_uses_sonnet(self, model_config):
        """Test synthesis task uses sonnet (balanced model)."""
        model = model_config.get_model(task="synthesis")
        # Should resolve to sonnet-based model
        assert "sonnet" in model.lower() or model == "sonnet"

    def test_no_task_uses_default_model(self, model_config):
        """Test no task specified uses default model."""
        default_model = model_config.get_model()
        # Should use provider's default model
        assert default_model is not None
        assert len(default_model) > 0


class TestSecretsManagement:
    """Test secrets management and LLM isolation."""

    @pytest.fixture
    def cred_manager(self):
        """Create fresh CredentialManager."""
        cm = CredentialManager()
        yield cm
        cm.clear_variables()

    def test_secret_invisible_to_llm(self, cred_manager):
        """Test secrets remain as placeholders for LLM context."""
        cred_manager.set_variable("db_password", "super_secret_123", VariableType.SECRET)
        cred_manager.set_variable("db_host", "prod-db-001", VariableType.CONFIG)

        query = "connect to @db_host using @db_password"

        # LLM context: resolve_secrets=False
        llm_query = cred_manager.resolve_variables(query, resolve_secrets=False)
        assert "@db_password" in llm_query  # Placeholder preserved
        assert "super_secret_123" not in llm_query  # Actual value hidden
        assert "prod-db-001" in llm_query  # Non-secret resolved

    def test_secret_visible_to_execution(self, cred_manager):
        """Test secrets are resolved for execution context."""
        cred_manager.set_variable("db_password", "super_secret_123", VariableType.SECRET)
        cred_manager.set_variable("db_host", "prod-db-001", VariableType.CONFIG)

        query = "connect to @db_host using @db_password"

        # Execution context: resolve_secrets=True (default)
        exec_query = cred_manager.resolve_variables(query, resolve_secrets=True)
        assert "@db_password" not in exec_query  # Placeholder resolved
        assert "super_secret_123" in exec_query  # Actual value present
        assert "prod-db-001" in exec_query  # Non-secret resolved

    def test_mixed_variable_resolution(self, cred_manager):
        """Test mixed secrets and config variables."""
        cred_manager.set_variable("api_key", "secret_key_123", VariableType.SECRET)
        cred_manager.set_variable("api_endpoint", "https://api.prod.example.com", VariableType.CONFIG)
        cred_manager.set_variable("db_host", "db-prod-001", VariableType.HOST)

        query = "curl @api_endpoint -H 'Authorization: @api_key' --data '{\"host\": \"@db_host\"}'"

        # LLM sees placeholders for secrets
        llm_query = cred_manager.resolve_variables(query, resolve_secrets=False)
        assert "@api_key" in llm_query
        assert "secret_key_123" not in llm_query
        assert "https://api.prod.example.com" in llm_query
        assert "db-prod-001" in llm_query

        # Execution sees all resolved
        exec_query = cred_manager.resolve_variables(query, resolve_secrets=True)
        assert "@api_key" not in exec_query
        assert "secret_key_123" in exec_query
        assert "https://api.prod.example.com" in exec_query
        assert "db-prod-001" in exec_query


class TestInteractiveSetup:
    """Test interactive setup functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_interactive_setup_not_triggered_when_config_exists(self, temp_config_dir, monkeypatch):
        """Test interactive setup is not triggered when config exists."""
        monkeypatch.setattr("athena_ai.llm.model_config.Path.home", lambda: temp_config_dir)

        # Create config file
        config_dir = temp_config_dir / ".athena"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({
            "provider": "openrouter",
            "models": {"openrouter": "anthropic/claude-3.5-sonnet"},
            "task_models": {"correction": "haiku"}
        }))

        # Should not trigger interactive setup
        config = ModelConfig(auto_configure=True)
        assert config.get_provider() == "openrouter"

    @patch('builtins.input')
    @patch('builtins.print')
    def test_interactive_setup_triggered_when_config_missing(self, mock_print, mock_input, temp_config_dir, monkeypatch):
        """Test interactive setup is triggered when config doesn't exist."""
        monkeypatch.setattr("athena_ai.llm.model_config.Path.home", lambda: temp_config_dir)

        # Mock user inputs
        mock_input.side_effect = [
            "1",    # Provider: openrouter
            "",     # Model: use default
            "n",    # Configure task models: no
            "n"     # Mixed providers: no
        ]

        # Should trigger interactive setup
        config = ModelConfig(auto_configure=True)

        # Verify config was created
        config_file = temp_config_dir / ".athena" / "config.json"
        assert config_file.exists()

        # Verify provider was set
        assert config.get_provider() == "openrouter"


class TestEnvironmentVariableClearing:
    """Test environment variable clearing when setting models."""

    def test_set_model_clears_env_var(self, monkeypatch, tmp_path):
        """Test that set_model clears corresponding environment variable."""
        monkeypatch.setattr("athena_ai.llm.model_config.Path.home", lambda: tmp_path)

        # Set environment variable
        os.environ["OPENROUTER_MODEL"] = "old-model"

        config = ModelConfig(auto_configure=False)
        config.set_model("openrouter", "new-model")

        # Environment variable should be cleared
        assert "OPENROUTER_MODEL" not in os.environ


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
