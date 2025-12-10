"""
Merlya Core - Logging configuration.

Uses loguru with emoji conventions for visual feedback.
"""

from __future__ import annotations

import sys
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
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    log_dir: Path | None = None,
    log_file: str = "merlya.log",
    max_size: str = "10 MB",
    retention: str = "7 days",
    colorize: bool = True,
    force: bool = False,
) -> Logger:
    """
    Configure logging for Merlya.

    Args:
        console_level: Console log level (DEBUG, INFO, WARNING, ERROR).
        file_level: File log level.
        log_dir: Directory for log files.
        log_file: Log file name.
        max_size: Max size before rotation.
        retention: How long to keep old logs.
        colorize: Enable console colors.
        force: Force reconfiguration even if already configured.

    Returns:
        Configured logger instance.
    """
    global _configured
    if _configured and not force:
        return logger

    # Reset handlers when forcing reconfigure
    logger.remove()

    # Ensure log directory exists
    log_path = log_dir or DEFAULT_LOG_DIR
    log_path.mkdir(parents=True, exist_ok=True)

    # Console handler - formatted for readability
    logger.add(
        sys.stderr,
        format="<level>{message}</level>",
        level=console_level.upper(),
        colorize=colorize,
        filter=lambda record: record["level"].name != "TRACE",
    )

    # File handler - detailed with timestamp
    logger.add(
        log_path / log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=file_level.upper(),
        rotation=max_size,
        retention=retention,
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
