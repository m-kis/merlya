"""Tests for config environment variable override support."""

import os
from pathlib import Path
from unittest.mock import patch

from merlya.config.loader import (
    ENV_CONFIG_MAP,
    _apply_env_overrides,
    _parse_env_value,
    load_config,
    reset_config,
)


class TestParseEnvValue:
    """Tests for _parse_env_value function."""

    def test_parses_true_values(self) -> None:
        for val in ("true", "True", "TRUE", "1", "yes", "on"):
            assert _parse_env_value(val, "any_key") is True

    def test_parses_false_values(self) -> None:
        for val in ("false", "False", "FALSE", "0", "no", "off"):
            assert _parse_env_value(val, "any_key") is False

    def test_parses_integer_for_timeout_keys(self) -> None:
        assert _parse_env_value("30", "timeout") == 30
        assert _parse_env_value("600", "pool_timeout") == 600
        assert _parse_env_value("8000", "max_tokens_per_call") == 8000

    def test_returns_string_for_invalid_int(self) -> None:
        assert _parse_env_value("not_a_number", "timeout") == "not_a_number"

    def test_parses_path_for_path_keys(self) -> None:
        result = _parse_env_value("~/test/path", "data_dir")
        assert isinstance(result, Path)
        assert str(result).endswith("test/path")

    def test_returns_string_for_regular_keys(self) -> None:
        assert _parse_env_value("anthropic", "provider") == "anthropic"


class TestApplyEnvOverrides:
    """Tests for _apply_env_overrides function."""

    def test_applies_single_override(self) -> None:
        with patch.dict(os.environ, {"MERLYA_PROVIDER": "anthropic"}):
            data = _apply_env_overrides({})
            assert data["model"]["provider"] == "anthropic"

    def test_applies_multiple_overrides(self) -> None:
        env = {
            "MERLYA_PROVIDER": "openai",
            "MERLYA_LANGUAGE": "fr",
            "MERLYA_SSH_POOL_TIMEOUT": "300",
        }
        with patch.dict(os.environ, env, clear=False):
            data = _apply_env_overrides({})
            assert data["model"]["provider"] == "openai"
            assert data["general"]["language"] == "fr"
            assert data["ssh"]["pool_timeout"] == 300

    def test_overrides_existing_values(self) -> None:
        initial_data = {"model": {"provider": "openrouter"}}
        with patch.dict(os.environ, {"MERLYA_PROVIDER": "anthropic"}):
            data = _apply_env_overrides(initial_data)
            assert data["model"]["provider"] == "anthropic"

    def test_preserves_unset_values(self) -> None:
        initial_data = {"model": {"model": "gpt-4"}}
        with patch.dict(os.environ, {"MERLYA_PROVIDER": "openai"}, clear=False):
            data = _apply_env_overrides(initial_data)
            assert data["model"]["model"] == "gpt-4"

    def test_creates_section_if_missing(self) -> None:
        with patch.dict(os.environ, {"MERLYA_SSH_POOL_TIMEOUT": "600"}):
            data = _apply_env_overrides({})
            assert "ssh" in data
            assert data["ssh"]["pool_timeout"] == 600


class TestEnvConfigMap:
    """Tests for ENV_CONFIG_MAP completeness."""

    def test_all_env_vars_start_with_prefix(self) -> None:
        for env_var in ENV_CONFIG_MAP:
            assert env_var.startswith("MERLYA_")

    def test_all_sections_are_valid(self) -> None:
        valid_sections = {"general", "model", "router", "ssh", "ui", "logging", "policy"}
        for env_var, (section, _) in ENV_CONFIG_MAP.items():
            assert section in valid_sections, f"{env_var} has invalid section: {section}"

    def test_has_key_config_overrides(self) -> None:
        # Ensure critical overrides are present
        assert "MERLYA_PROVIDER" in ENV_CONFIG_MAP
        assert "MERLYA_MODEL" in ENV_CONFIG_MAP
        assert "MERLYA_LANGUAGE" in ENV_CONFIG_MAP
        assert "MERLYA_LOG_LEVEL" in ENV_CONFIG_MAP


class TestLoadConfigWithEnvOverride:
    """Integration tests for load_config with env overrides."""

    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_env_overrides_default_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        # Don't create file - test first run

        with patch.dict(os.environ, {"MERLYA_PROVIDER": "anthropic"}):
            config = load_config(config_path)
            assert config.model.provider == "anthropic"

    def test_env_overrides_file_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("model:\n  provider: openrouter\n")

        with patch.dict(os.environ, {"MERLYA_PROVIDER": "openai"}):
            config = load_config(config_path)
            assert config.model.provider == "openai"

    def test_boolean_env_override(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("policy:\n  require_confirmation_for_write: true\n")

        with patch.dict(os.environ, {"MERLYA_REQUIRE_CONFIRM": "false"}):
            config = load_config(config_path)
            assert config.policy.require_confirmation_for_write is False
