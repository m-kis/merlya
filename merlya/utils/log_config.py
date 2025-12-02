"""
Logging configuration for Merlya.

Provides configurable logging with:
- Log directory management
- Log rotation (size and time-based)
- Verbosity levels
- Multiple log formats
- Persistent configuration
"""
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional


class LogLevel(str, Enum):
    """Log verbosity levels."""
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_string(cls, level: str) -> "LogLevel":
        """Parse log level from string (case-insensitive)."""
        level = level.upper()
        try:
            return cls(level)
        except ValueError:
            # Handle common aliases
            aliases = {
                "WARN": cls.WARNING,
                "ERR": cls.ERROR,
                "CRIT": cls.CRITICAL,
                "FATAL": cls.CRITICAL,
            }
            if level in aliases:
                return aliases[level]
            raise ValueError(f"Unknown log level: {level}") from None


class RotationStrategy(str, Enum):
    """Log rotation strategies."""
    SIZE = "size"       # Rotate based on file size
    TIME = "time"       # Rotate based on time
    BOTH = "both"       # Rotate on either condition


@dataclass
class LogConfig:
    """
    Configuration for Merlya logging.

    Attributes:
        log_dir: Directory for log files (default: ~/.merlya/logs)
        app_log_name: Main application log filename
        audit_log_name: Security audit log filename
        console_level: Log level for console output
        file_level: Log level for file output
        rotation_size: Max size before rotation (e.g., "10 MB", "100 KB")
        rotation_time: Time-based rotation (e.g., "1 day", "12 hours", "1 week")
        retention: How long to keep old logs (e.g., "7 days", "4 weeks")
        max_files: Maximum number of rotated files to keep
        compression: Compress rotated files (zip, gz, or None)
        json_logs: Use JSON format for file logs
        include_caller: Include caller info (file:function:line)
        use_emoji: Use emoji prefixes in console output
    """
    # Directory settings
    log_dir: str = ""
    app_log_name: str = "app.log"
    audit_log_name: str = "audit.log"

    # Verbosity
    console_level: str = "WARNING"
    file_level: str = "DEBUG"

    # Rotation settings
    rotation_size: str = "10 MB"
    rotation_time: str = "1 day"
    rotation_strategy: str = "size"
    retention: str = "1 week"
    max_files: int = 10
    compression: Optional[str] = "gz"

    # Format settings
    json_logs: bool = False
    include_caller: bool = True
    use_emoji: bool = True

    # Console settings
    console_enabled: bool = False  # Only enable with --verbose

    # Valid values for validation
    _VALID_COMPRESSION: ClassVar[frozenset] = frozenset({"zip", "gz", None})
    _VALID_STRATEGIES: ClassVar[frozenset] = frozenset({"size", "time", "both"})

    def __post_init__(self):
        """Validate and set defaults."""
        # Set default log directory
        if not self.log_dir:
            self.log_dir = str(Path.home() / ".merlya" / "logs")

        # Validate log level
        try:
            LogLevel.from_string(self.console_level)
        except ValueError as e:
            raise ValueError(f"Invalid console_level: {e}") from e

        try:
            LogLevel.from_string(self.file_level)
        except ValueError as e:
            raise ValueError(f"Invalid file_level: {e}") from e

        # Validate rotation strategy
        if self.rotation_strategy not in self._VALID_STRATEGIES:
            raise ValueError(
                f"rotation_strategy must be one of {set(self._VALID_STRATEGIES)}, "
                f"got: {self.rotation_strategy!r}"
            )

        # Validate compression
        if self.compression not in self._VALID_COMPRESSION:
            raise ValueError(
                f"compression must be one of {set(self._VALID_COMPRESSION)}, "
                f"got: {self.compression!r}"
            )

        # Validate rotation_size format
        self._validate_size_format(self.rotation_size)

        # Validate max_files
        if self.max_files < 1:
            raise ValueError(f"max_files must be >= 1, got: {self.max_files}")

    def _validate_size_format(self, size_str: str) -> None:
        """Validate size format like '10 MB' or '100 KB'."""
        parts = size_str.strip().split()
        if len(parts) != 2:
            raise ValueError(f"Invalid size format: {size_str!r} (expected: '10 MB')")

        try:
            value = float(parts[0])
            if value <= 0:
                raise ValueError(f"Size must be positive: {size_str!r}")
        except ValueError as e:
            raise ValueError(f"Invalid size value: {parts[0]!r}") from e

        valid_units = {"B", "KB", "MB", "GB", "TB"}
        if parts[1].upper() not in valid_units:
            raise ValueError(f"Invalid size unit: {parts[1]!r} (valid: {valid_units})")

    @property
    def log_path(self) -> Path:
        """Get the full path to the main log file."""
        return Path(self.log_dir) / self.app_log_name

    @property
    def audit_log_path(self) -> Path:
        """Get the full path to the audit log file."""
        return Path(self.log_dir) / self.audit_log_name

    def ensure_log_dir(self) -> Path:
        """Create log directory if it doesn't exist."""
        log_dir = Path(self.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "log_dir": self.log_dir,
            "app_log_name": self.app_log_name,
            "audit_log_name": self.audit_log_name,
            "console_level": self.console_level,
            "file_level": self.file_level,
            "rotation_size": self.rotation_size,
            "rotation_time": self.rotation_time,
            "rotation_strategy": self.rotation_strategy,
            "retention": self.retention,
            "max_files": self.max_files,
            "compression": self.compression,
            "json_logs": self.json_logs,
            "include_caller": self.include_caller,
            "use_emoji": self.use_emoji,
            "console_enabled": self.console_enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogConfig":
        """Create from dictionary."""
        # Filter only known fields
        known_fields = {
            "log_dir", "app_log_name", "audit_log_name",
            "console_level", "file_level",
            "rotation_size", "rotation_time", "rotation_strategy",
            "retention", "max_files", "compression",
            "json_logs", "include_caller", "use_emoji", "console_enabled",
        }
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


# Config file location
CONFIG_FILE = Path.home() / ".merlya" / "log_config.json"


def load_log_config() -> LogConfig:
    """
    Load logging configuration.

    Priority:
    1. Environment variables (MERLYA_LOG_*)
    2. Config file (~/.merlya/log_config.json)
    3. Defaults
    """
    config_data: Dict[str, Any] = {}

    # Load from file if exists
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass  # Use defaults

    # Override with environment variables
    env_mappings = {
        "MERLYA_LOG_DIR": "log_dir",
        "MERLYA_LOG_LEVEL": "console_level",
        "MERLYA_LOG_FILE_LEVEL": "file_level",
        "MERLYA_LOG_ROTATION_SIZE": "rotation_size",
        "MERLYA_LOG_ROTATION_TIME": "rotation_time",
        "MERLYA_LOG_RETENTION": "retention",
        "MERLYA_LOG_MAX_FILES": "max_files",
        "MERLYA_LOG_COMPRESSION": "compression",
        "MERLYA_LOG_JSON": "json_logs",
        "MERLYA_LOG_EMOJI": "use_emoji",
    }

    for env_var, config_key in env_mappings.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Handle type conversion
            if config_key in ("json_logs", "use_emoji", "include_caller", "console_enabled"):
                config_data[config_key] = value.lower() in ("1", "true", "yes", "on")
            elif config_key == "max_files":
                try:
                    config_data[config_key] = int(value)
                except ValueError:
                    pass
            elif config_key == "compression":
                config_data[config_key] = value if value.lower() not in ("none", "") else None
            else:
                config_data[config_key] = value

    return LogConfig.from_dict(config_data)


def save_log_config(config: LogConfig) -> bool:
    """
    Save logging configuration to file.

    Args:
        config: LogConfig to save

    Returns:
        True if saved successfully
    """
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config.to_dict(), f, indent=2)
        return True
    except OSError:
        return False


def get_log_config() -> LogConfig:
    """Get the current logging configuration (cached)."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_log_config()
    return _cached_config


def reset_log_config() -> None:
    """Reset the cached configuration."""
    global _cached_config
    _cached_config = None


# Cached config instance
_cached_config: Optional[LogConfig] = None
