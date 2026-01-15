"""
Merlya Core - Logging configuration.

Uses loguru with emoji conventions for visual feedback.
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger

# Remove default handler
logger.remove()

# Prevent duplicate configuration
_configured = False

# Default log directory
DEFAULT_LOG_DIR = Path.home() / ".merlya" / "logs"


@dataclass
class LoggingConfig:
    """Configuration for logging.

    Groups configuration parameters to reduce configure_logging() complexity.
    """

    console_level: str = "INFO"
    file_level: str = "DEBUG"
    log_dir: Path | None = None
    log_file: str = "merlya.log"
    max_size: str = "10 MB"
    retention: str = "7 days"
    colorize: bool = True
    force: bool = False


class LogEmoji:
    """Emoji constants for logging (from CONTRIBUTING.md)."""

    # Status
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"

    # Actions
    THINKING = "🧠"
    EXECUTING = "⚡"
    SCAN = "🔍"

    # Security
    SECURITY = "🔒"
    QUESTION = "❓"
    CRITICAL = "🚨"

    # Resources
    HOST = "🖥️"
    NETWORK = "🌐"
    DATABASE = "🗄️"
    FILE = "📁"
    LOG = "📋"
    CONFIG = "⚙️"
    TIMER = "⏱️"


def configure_logging(
    config: LoggingConfig | None = None,
    *,
    # Legacy parameters for backwards compatibility (deprecated)
    console_level: str | None = None,
    file_level: str | None = None,
    log_dir: Path | None = None,
    log_file: str | None = None,
    max_size: str | None = None,
    retention: str | None = None,
    colorize: bool | None = None,
    force: bool | None = None,
) -> Logger:
    """
    Configure logging for Merlya.

    Args:
        config: Logging configuration (preferred).
        console_level: (Deprecated) Use config.console_level instead.
        file_level: (Deprecated) Use config.file_level instead.
        log_dir: (Deprecated) Use config.log_dir instead.
        log_file: (Deprecated) Use config.log_file instead.
        max_size: (Deprecated) Use config.max_size instead.
        retention: (Deprecated) Use config.retention instead.
        colorize: (Deprecated) Use config.colorize instead.
        force: (Deprecated) Use config.force instead.

    Returns:
        Configured logger instance.
    """
    global _configured

    # Handle backwards compatibility
    if config is not None:
        _console_level = config.console_level
        _file_level = config.file_level
        _log_dir = config.log_dir
        _log_file = config.log_file
        _max_size = config.max_size
        _retention = config.retention
        _colorize = config.colorize
        _force = config.force
    else:
        # Legacy mode - emit deprecation warning if using individual params
        legacy_params = [
            console_level,
            file_level,
            log_dir,
            log_file,
            max_size,
            retention,
            colorize,
            force,
        ]
        if any(p is not None for p in legacy_params):
            warnings.warn(
                "Passing individual parameters to configure_logging() is deprecated. "
                "Use LoggingConfig instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        _console_level = console_level if console_level is not None else "INFO"
        _file_level = file_level if file_level is not None else "DEBUG"
        _log_dir = log_dir
        _log_file = log_file if log_file is not None else "merlya.log"
        _max_size = max_size if max_size is not None else "10 MB"
        _retention = retention if retention is not None else "7 days"
        _colorize = colorize if colorize is not None else True
        _force = force if force is not None else False

    if _configured and not _force:
        return logger

    # Reset handlers when forcing reconfigure
    logger.remove()

    # Ensure log directory exists
    log_path = _log_dir or DEFAULT_LOG_DIR
    log_path.mkdir(parents=True, exist_ok=True)

    # Console handler - formatted for readability
    logger.add(
        sys.stderr,
        format="<level>{message}</level>",
        level=_console_level.upper(),
        colorize=_colorize,
        filter=lambda record: record["level"].name != "TRACE",
    )

    # File handler - detailed with timestamp
    logger.add(
        log_path / _log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=_file_level.upper(),
        rotation=_max_size,
        retention=_retention,
        compression="gz",
        enqueue=True,  # Thread-safe
    )

    _configured = True
    return logger


def get_logger() -> Logger:
    """Get the configured logger instance."""
    return logger


# Convenience functions with emojis
def log_success(message: str) -> None:
    """Log success message with emoji."""
    logger.info(f"{LogEmoji.SUCCESS} {message}")


def log_error(message: str) -> None:
    """Log error message with emoji."""
    logger.error(f"{LogEmoji.ERROR} {message}")


def log_warning(message: str) -> None:
    """Log warning message with emoji."""
    logger.warning(f"{LogEmoji.WARNING} {message}")


def log_info(message: str) -> None:
    """Log info message with emoji."""
    logger.info(f"{LogEmoji.INFO} {message}")


def log_thinking(message: str) -> None:
    """Log AI thinking/processing."""
    logger.info(f"{LogEmoji.THINKING} {message}")


def log_executing(message: str) -> None:
    """Log command execution."""
    logger.info(f"{LogEmoji.EXECUTING} {message}")


def log_scan(message: str) -> None:
    """Log scan/discovery."""
    logger.info(f"{LogEmoji.SCAN} {message}")


def log_host(message: str) -> None:
    """Log host-related action."""
    logger.info(f"{LogEmoji.HOST} {message}")


def log_network(message: str) -> None:
    """Log network operation."""
    logger.info(f"{LogEmoji.NETWORK} {message}")


def log_security(message: str) -> None:
    """Log security-related message."""
    logger.info(f"{LogEmoji.SECURITY} {message}")


def log_critical(message: str) -> None:
    """Log critical alert."""
    logger.critical(f"{LogEmoji.CRITICAL} {message}")


def enable_http_debug() -> None:
    """
    Enable HTTP request/response debugging for API troubleshooting.

    This enables logging for httpx (used by LLM providers) to see
    the full request/response cycle. Useful for debugging tool_call_id
    issues with providers like Mistral.

    Usage:
        from merlya.core.logging import enable_http_debug
        enable_http_debug()
    """
    import logging

    # Enable httpx logging
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.DEBUG)

    # Create a handler that outputs to stderr
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("🌐 HTTP | %(asctime)s | %(message)s", datefmt="%H:%M:%S")
    )
    httpx_logger.addHandler(handler)

    # Also enable httpcore for lower-level details
    httpcore_logger = logging.getLogger("httpcore")
    httpcore_logger.setLevel(logging.DEBUG)
    httpcore_logger.addHandler(handler)

    logger.info("🌐 HTTP debug logging enabled - all API requests will be logged")
