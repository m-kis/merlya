"""
Merlya Config - Configuration loader.

Loads and saves configuration from YAML file.
Supports environment variable overrides with MERLYA_* prefix.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from merlya.config.models import (
    GeneralConfig,
    LLMConfig,
    LoggingConfig,
    MCPConfig,
    PolicyConfig,
    RouterConfig,
    SSHConfig,
    UIConfig,
)

# Environment variable prefix for config overrides
ENV_PREFIX = "MERLYA_"

# Mapping of environment variables to config paths
# Format: ENV_VAR -> (config_section, config_key)
ENV_CONFIG_MAP: dict[str, tuple[str, str]] = {
    # General
    "MERLYA_LANGUAGE": ("general", "language"),
    "MERLYA_LOG_LEVEL": ("general", "log_level"),
    "MERLYA_DATA_DIR": ("general", "data_dir"),
    # Model/LLM
    "MERLYA_PROVIDER": ("model", "provider"),
    "MERLYA_MODEL": ("model", "model"),
    "MERLYA_REASONING_MODEL": ("model", "reasoning_model"),
    "MERLYA_FAST_MODEL": ("model", "fast_model"),
    "MERLYA_TIMEOUT": ("model", "timeout"),
    "MERLYA_BASE_URL": ("model", "base_url"),
    # Router
    "MERLYA_ROUTER_TYPE": ("router", "type"),
    "MERLYA_ROUTER_FALLBACK": ("router", "llm_fallback"),
    # SSH
    "MERLYA_SSH_POOL_TIMEOUT": ("ssh", "pool_timeout"),
    "MERLYA_SSH_CONNECT_TIMEOUT": ("ssh", "connect_timeout"),
    "MERLYA_SSH_COMMAND_TIMEOUT": ("ssh", "command_timeout"),
    "MERLYA_SSH_USER": ("ssh", "default_user"),
    "MERLYA_SSH_KEY": ("ssh", "default_key"),
    # UI
    "MERLYA_THEME": ("ui", "theme"),
    "MERLYA_MARKDOWN": ("ui", "markdown"),
    # Logging
    "MERLYA_CONSOLE_LOG_LEVEL": ("logging", "console_level"),
    "MERLYA_FILE_LOG_LEVEL": ("logging", "file_level"),
    # Policy
    "MERLYA_CONTEXT_TIER": ("policy", "context_tier"),
    "MERLYA_MAX_TOKENS": ("policy", "max_tokens_per_call"),
    "MERLYA_REQUIRE_CONFIRM": ("policy", "require_confirmation_for_write"),
    "MERLYA_AUDIT_LOGGING": ("policy", "audit_logging"),
}

# Default config path
DEFAULT_CONFIG_PATH = Path.home() / ".merlya" / "config.yaml"


class Config(BaseModel):
    """Complete application configuration."""

    model_config = ConfigDict(extra="ignore")

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    model: LLMConfig = Field(default_factory=LLMConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    ssh: SSHConfig = Field(default_factory=SSHConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    # Internal state
    _path: Path | None = None
    _first_run: bool = False

    @property
    def is_first_run(self) -> bool:
        """Check if this is the first run."""
        return self._first_run

    def save(self, path: Path | None = None) -> None:
        """
        Save configuration to YAML file.

        Args:
            path: Optional path override.
        """
        save_path = path or self._path or DEFAULT_CONFIG_PATH
        save_config(self, save_path)


# Singleton instance with thread-safety
_config_instance: Config | None = None
_config_lock = threading.Lock()


def _parse_env_value(value: str, key: str) -> Any:
    """
    Parse environment variable value to appropriate type.

    Args:
        value: Raw string value from environment.
        key: Config key name for type inference.

    Returns:
        Parsed value (int, bool, Path, or str).
    """
    # Boolean values
    if value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False

    # Integer values (for timeout, max_tokens, etc.)
    int_keys = {
        "timeout",
        "pool_timeout",
        "connect_timeout",
        "command_timeout",
        "max_tokens_per_call",
        "max_hosts_per_skill",
        "max_parallel_subagents",
        "subagent_timeout",
        "max_size_mb",
        "max_files",
        "retention_days",
        "max_messages_in_memory",
    }
    if key in int_keys:
        try:
            return int(value)
        except ValueError:
            pass

    # Path values
    path_keys = {"data_dir", "default_key"}
    if key in path_keys:
        return Path(value).expanduser()

    return value


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """
    Apply environment variable overrides to config data.

    Environment variables with MERLYA_* prefix override config values.

    Args:
        data: Config data dict loaded from YAML.

    Returns:
        Config data with env overrides applied.
    """
    overrides_applied = []

    for env_var, (section, key) in ENV_CONFIG_MAP.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Ensure section exists
            if section not in data:
                data[section] = {}

            # Parse and set value
            parsed_value = _parse_env_value(value, key)
            data[section][key] = parsed_value
            overrides_applied.append(f"{env_var}={value}")

    if overrides_applied:
        logger.debug(f"Config env overrides: {', '.join(overrides_applied)}")

    return data


def load_config(path: Path | None = None) -> Config:
    """
    Load configuration from YAML file with environment variable overrides.

    Environment variables with MERLYA_* prefix override config values.
    Example: MERLYA_PROVIDER=anthropic overrides model.provider

    Args:
        path: Path to config file. Defaults to ~/.merlya/config.yaml

    Returns:
        Loaded configuration.
    """
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.debug(f"Config file not found: {config_path}")
        # Start with empty data, apply env overrides
        data = _apply_env_overrides({})
        config = Config.model_validate(data)
        config._path = config_path
        config._first_run = True
        return config

    try:
        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Apply environment variable overrides
        data = _apply_env_overrides(data)

        config = Config.model_validate(data)
        config._path = config_path
        config._first_run = False

        logger.debug(f"Config loaded from: {config_path}")
        return config

    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in config: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise


def _convert_paths_to_strings(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert Path objects to strings for YAML serialization."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, Path):
            result[key] = str(value)
        elif isinstance(value, dict):
            result[key] = _convert_paths_to_strings(value)
        else:
            result[key] = value
    return result


def save_config(config: Config, path: Path | None = None) -> None:
    """
    Save configuration to YAML file.

    Args:
        config: Configuration to save.
        path: Path to save to.
    """
    save_path = path or DEFAULT_CONFIG_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict, excluding internal fields
    data = config.model_dump(exclude_none=True, exclude_unset=False)

    # Convert Path objects to strings for YAML compatibility
    data = _convert_paths_to_strings(data)

    # Add header comment
    yaml_content = "# Merlya Configuration\n# Edit this file to customize settings\n\n"
    yaml_content += yaml.dump(data, default_flow_style=False, sort_keys=False)

    with save_path.open("w", encoding="utf-8") as f:
        f.write(yaml_content)

    logger.debug(f"Config saved to: {save_path}")


def get_config(path: Path | None = None) -> Config:
    """
    Get configuration singleton (thread-safe).

    Args:
        path: Optional path for first load.

    Returns:
        Configuration instance.
    """
    global _config_instance

    # Double-checked locking pattern for thread safety
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                _config_instance = load_config(path)

    return _config_instance


def reset_config() -> None:
    """Reset configuration singleton (for tests, thread-safe)."""
    global _config_instance
    with _config_lock:
        _config_instance = None


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Deep merge two configuration dicts.

    Args:
        base: Base configuration.
        override: Override values.

    Returns:
        Merged configuration.
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value

    return result
