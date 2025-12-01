"""
Tests for Model Configuration.

Tests the model configuration validation and auto-fix features.
"""

import json
import tempfile
from pathlib import Path

import pytest

from athena_ai.llm.model_config import ModelConfig


@pytest.fixture
def temp_config_dir(monkeypatch):
    """Create temporary config directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / ".athena"
        config_dir.mkdir(parents=True, exist_ok=True)
        # Mock home directory to use temp dir
        monkeypatch.setattr(Path, "home", lambda: Path(tmpdir))
        yield config_dir


class TestModelConfigValidation:
    """Tests for model configuration validation and auto-fix."""

    def test_invalid_model_auto_fixed(self, temp_config_dir):
        """Invalid model names should be auto-fixed to defaults."""
        # Create config with invalid model
        config_file = temp_config_dir / "config.json"
        invalid_config = {
            "provider": "openrouter",
            "models": {
                "openrouter": "provider",  # Invalid!
                "ollama": "gemma3:12b-it-qat"
            }
        }
        with open(config_file, 'w') as f:
            json.dump(invalid_config, f)

        # Load config - should auto-fix
        config = ModelConfig()

        # Check that invalid model was fixed
        assert config.get_model("openrouter") != "provider"
        assert config.get_model("openrouter") == ModelConfig.DEFAULT_MODELS["openrouter"]

        # Valid model should remain unchanged
        assert config.get_model("ollama") == "gemma3:12b-it-qat"

    def test_null_model_auto_fixed(self, temp_config_dir):
        """Null/None/empty model values should be auto-fixed."""
        config_file = temp_config_dir / "config.json"
        invalid_configs = [
            {"provider": "openrouter", "models": {"openrouter": ""}},
            {"provider": "openrouter", "models": {"openrouter": "null"}},
            {"provider": "openrouter", "models": {"openrouter": "none"}},
            {"provider": "openrouter", "models": {"openrouter": "model"}},
        ]

        for invalid_config in invalid_configs:
            with open(config_file, 'w') as f:
                json.dump(invalid_config, f)

            # Reset and reload
            config = ModelConfig()
            model = config.get_model("openrouter")

            # Should be fixed to default
            assert model == ModelConfig.DEFAULT_MODELS["openrouter"]
            assert model != invalid_config["models"]["openrouter"]

    def test_missing_models_section(self, temp_config_dir):
        """Missing 'models' section should be added."""
        config_file = temp_config_dir / "config.json"
        minimal_config = {
            "provider": "openrouter"
            # No "models" section
        }
        with open(config_file, 'w') as f:
            json.dump(minimal_config, f)

        config = ModelConfig()

        # Should have models section with defaults
        assert "models" in config.config
        assert config.get_model("openrouter") == ModelConfig.DEFAULT_MODELS["openrouter"]

    def test_valid_config_unchanged(self, temp_config_dir):
        """Valid configuration should not be modified."""
        config_file = temp_config_dir / "config.json"
        valid_config = {
            "provider": "openrouter",
            "models": {
                "openrouter": "anthropic/claude-3.5-sonnet",
                "ollama": "llama3"
            },
            "task_models": {
                "correction": "haiku",
                "planning": "opus"
            }
        }
        with open(config_file, 'w') as f:
            json.dump(valid_config, f)

        config = ModelConfig()

        # Should remain unchanged
        assert config.get_model("openrouter") == "anthropic/claude-3.5-sonnet"
        assert config.get_model("ollama") == "llama3"
        assert config.config["task_models"]["correction"] == "haiku"
        assert config.config["task_models"]["planning"] == "opus"


class TestModelConfigGetCurrentConfig:
    """Tests for get_current_config method."""

    def test_get_current_config_returns_correct_provider(self, temp_config_dir):
        """get_current_config should return correct provider."""
        config = ModelConfig()
        current = config.get_current_config()

        assert "provider" in current
        assert current["provider"] == "openrouter"

    def test_get_current_config_returns_correct_model(self, temp_config_dir):
        """get_current_config should return correct model for provider."""
        config = ModelConfig()
        config.set_model("openrouter", "anthropic/claude-3.5-sonnet")

        current = config.get_current_config()

        assert "model" in current
        assert current["model"] == "anthropic/claude-3.5-sonnet"

    def test_get_current_config_includes_task_models(self, temp_config_dir):
        """get_current_config should include task_models."""
        config = ModelConfig()
        config.set_task_model("correction", "haiku")

        current = config.get_current_config()

        assert "task_models" in current
        assert current["task_models"]["correction"] == "haiku"


class TestModelConfigSetModel:
    """Tests for set_model method."""

    def test_set_model_saves_to_config(self, temp_config_dir):
        """set_model should save to config file."""
        config = ModelConfig()
        config.set_model("openrouter", "anthropic/claude-3.5-sonnet")

        # Reload to verify persistence
        config2 = ModelConfig()
        assert config2.get_model("openrouter") == "anthropic/claude-3.5-sonnet"

    def test_set_model_invalid_provider_raises(self, temp_config_dir):
        """set_model should raise for invalid provider."""
        config = ModelConfig()

        with pytest.raises(ValueError, match="Unknown provider"):
            config.set_model("invalid_provider", "some-model")


class TestModelConfigTaskModels:
    """Tests for task-specific model configuration."""

    def test_set_task_model_valid(self, temp_config_dir):
        """set_task_model should work for valid tasks."""
        config = ModelConfig()
        config.set_task_model("correction", "haiku")

        assert config.get_task_models()["correction"] == "haiku"

    def test_set_task_model_invalid_raises(self, temp_config_dir):
        """set_task_model should raise for invalid tasks."""
        config = ModelConfig()

        with pytest.raises(ValueError, match="Invalid task"):
            config.set_task_model("invalid_task", "haiku")

    def test_get_task_models_returns_dict(self, temp_config_dir):
        """get_task_models should return dictionary."""
        config = ModelConfig()
        task_models = config.get_task_models()

        assert isinstance(task_models, dict)


class TestModelConfigPriorityMapping:
    """Tests for priority-based model selection."""

    def test_priority_task_map_exists(self):
        """PRIORITY_TASK_MAP should exist and cover all priorities."""
        assert hasattr(ModelConfig, "PRIORITY_TASK_MAP")
        assert "P0" in ModelConfig.PRIORITY_TASK_MAP
        assert "P1" in ModelConfig.PRIORITY_TASK_MAP
        assert "P2" in ModelConfig.PRIORITY_TASK_MAP
        assert "P3" in ModelConfig.PRIORITY_TASK_MAP

    def test_p0_uses_fast_model(self, temp_config_dir):
        """P0 should use fast model (correction task)."""
        # P0 maps to correction task which uses haiku
        # temp_config_dir fixture ensures clean config state
        assert ModelConfig.PRIORITY_TASK_MAP["P0"] == "correction"

    def test_p3_uses_thorough_model(self, temp_config_dir):
        """P3 should use thorough model (planning task)."""
        # P3 maps to planning task which uses opus
        # temp_config_dir fixture ensures clean config state
        assert ModelConfig.PRIORITY_TASK_MAP["P3"] == "planning"

    def test_get_model_for_priority_p0(self, temp_config_dir):
        """get_model_for_priority(P0) should return fast model."""
        config = ModelConfig()
        model = config.get_model_for_priority("P0")

        # Should be a haiku model (fast)
        assert "haiku" in model.lower() or model == config.get_model(task="correction")

    def test_get_model_for_priority_p3(self, temp_config_dir):
        """get_model_for_priority(P3) should return thorough model."""
        config = ModelConfig()
        model = config.get_model_for_priority("P3")

        # Should be an opus model (thorough)
        assert "opus" in model.lower() or model == config.get_model(task="planning")

    def test_get_model_for_priority_unknown_defaults_to_synthesis(self, temp_config_dir):
        """Unknown priority should default to synthesis task."""
        config = ModelConfig()
        model = config.get_model_for_priority("UNKNOWN")

        # Should fall back to synthesis model (balanced)
        assert model == config.get_model(task="synthesis")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
