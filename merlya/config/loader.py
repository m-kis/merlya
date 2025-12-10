"""
Merlya Config - Configuration loader.

Loads and saves configuration from YAML file.
"""

from __future__ import annotations

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


def load_config(path: Path | None = None) -> Config:
    """
    Load configuration from YAML file.

    Args:
        path: Path to config file. Defaults to ~/.merlya/config.yaml

    Returns:
        Loaded configuration.
    """
    config_path = path or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.debug(f"Config file not found: {config_path}")
        config = Config()
        config._path = config_path
        config._first_run = True
        return config

    try:
        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

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
