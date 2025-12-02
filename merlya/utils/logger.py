"""
Centralized logging for Merlya.

Provides:
- Configurable log levels and rotation
- Session-specific logging
- Sensitive data redaction
- Multiple output targets (file, console)

Configuration is loaded from ~/.merlya/log_config.json or environment variables.
See log_config.py for details.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from merlya.utils.security import redact_sensitive_info


def use_emoji_logs() -> bool:
    """
    Check if emoji prefixes should be used in log messages.

    Returns True unless USE_EMOJI_LOGS environment variable is set to "0" or "false".
    Production environments can disable emojis by setting USE_EMOJI_LOGS=0.
    """
    value = os.environ.get("USE_EMOJI_LOGS", "1").lower()
    return value not in ("0", "false", "no", "off")


# Mapping of emoji prefixes to ASCII alternatives
_EMOJI_TO_ASCII = {
    "🔄": "[RETRY]",
    "⚠️": "[WARN]",
    "💀": "[DEAD]",
    "⏱️": "[TIMEOUT]",
    "🌐": "[CONNECT]",
    "✓": "[OK]",
    "✅": "[OK]",
    "❌": "[ERROR]",
    "🔒": "[CLOSE]",
    "🧹": "[CLEANUP]",
    "🔐": "[SECRET]",
    "📁": "[FILE]",
    "📊": "[STATS]",
}


def log_prefix(emoji: str) -> str:
    """
    Return the appropriate log prefix based on USE_EMOJI_LOGS setting.

    Args:
        emoji: The emoji to use when emoji logs are enabled.

    Returns:
        The emoji if USE_EMOJI_LOGS is enabled, otherwise the ASCII equivalent
        (or empty string if no mapping exists).
    """
    if use_emoji_logs():
        return emoji
    return _EMOJI_TO_ASCII.get(emoji, "")


def _get_log_config():
    """Get log configuration (lazy import to avoid circular deps)."""
    from merlya.utils.log_config import get_log_config
    return get_log_config()


def setup_logger(
    verbose: bool = False,
    session_id: Optional[str] = None,
    config: Optional[Any] = None,
) -> None:
    """
    Configure the logger with session-specific logging.

    Rules:
    1. FILE: Always log to ~/.merlya/logs/app.log (rotated) with session_id prefix.
    2. CONSOLE:
       - If verbose: Log DEBUG+ to stderr.
       - If NOT verbose: DO NOT log to stderr (DisplayManager handles UI).

    Args:
        verbose: Enable console logging
        session_id: Optional session ID to add to log format
        config: Optional LogConfig override (for testing)
    """
    logger.remove()

    # Get configuration
    if config is None:
        config = _get_log_config()

    # Ensure log directory exists
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Build log file path
    log_path = log_dir / config.app_log_name

    # Custom format function to handle optional session_id
    def format_record(record):
        """Format log record with optional session_id."""
        sid = record["extra"].get("session_id", "")

        if config.json_logs:
            # JSON format for structured logging
            log_entry = {
                "timestamp": record["time"].isoformat(),
                "level": record["level"].name,
                "message": record["message"],
                "module": record["name"],
                "function": record["function"],
                "line": record["line"],
            }
            if sid:
                log_entry["session_id"] = sid
            return json.dumps(log_entry) + "\n"
        else:
            # Standard format
            if config.include_caller:
                if sid:
                    return (
                        "{time:YYYY-MM-DD HH:mm:ss} | " + sid +
                        " | {level: <8} | {name}:{function}:{line} - {message}\n"
                    )
                else:
                    return (
                        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                        "{name}:{function}:{line} - {message}\n"
                    )
            else:
                if sid:
                    return "{time:YYYY-MM-DD HH:mm:ss} | " + sid + " | {level: <8} | {message}\n"
                else:
                    return "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}\n"

    # Build rotation parameter based on strategy
    rotation = config.rotation_size
    if config.rotation_strategy == "time":
        rotation = config.rotation_time
    elif config.rotation_strategy == "both":
        # Loguru doesn't support both, use size as primary
        rotation = config.rotation_size

    # File Logging (Always active, detailed)
    logger.add(
        log_path,
        rotation=rotation,
        retention=config.retention,
        level=config.file_level,
        format=format_record,
        compression=config.compression,
        enqueue=True,
    )

    # Console Logging (Only if verbose or explicitly enabled)
    if verbose or config.console_enabled:
        console_format = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        logger.add(
            sys.stderr,
            format=console_format,
            level=config.console_level if not verbose else "DEBUG",
            colorize=True,
        )

    # Global Redaction Filter
    def _redact_value(value, _seen=None):
        """Recursively redact sensitive info from a value."""
        if _seen is None:
            _seen = set()

        value_id = id(value)
        if value_id in _seen:
            return "[circular reference]"

        if isinstance(value, str):
            return redact_sensitive_info(value)
        elif isinstance(value, dict):
            _seen.add(value_id)
            result = {
                redact_sensitive_info(k) if isinstance(k, str) else k: _redact_value(v, _seen)
                for k, v in value.items()
            }
            _seen.discard(value_id)
            return result
        elif isinstance(value, list):
            _seen.add(value_id)
            result = [_redact_value(item, _seen) for item in value]
            _seen.discard(value_id)
            return result
        elif isinstance(value, tuple):
            _seen.add(value_id)
            result = tuple(_redact_value(item, _seen) for item in value)
            _seen.discard(value_id)
            return result
        elif isinstance(value, (set, frozenset)):
            _seen.add(value_id)
            result_list = [_redact_value(item, _seen) for item in value]
            _seen.discard(value_id)
            return result_list
        else:
            return value

    def redaction_filter(record):
        """Redact sensitive info from all logs."""
        try:
            record["message"] = redact_sensitive_info(record["message"])
        except Exception:
            record["message"] = "[REDACTED]"

        if "extra" in record and record["extra"]:
            try:
                for key in list(record["extra"].keys()):
                    try:
                        record["extra"][key] = _redact_value(record["extra"][key])
                    except Exception:
                        record["extra"][key] = "[REDACTED]"
            except Exception:
                record["extra"] = {"_redacted": "[REDACTED]"}

        return True

    logger.configure(patcher=redaction_filter)


def get_session_logger(session_id: str):
    """
    Get a logger bound to a specific session ID.

    This allows filtering logs by session in multi-instance scenarios.

    Args:
        session_id: Unique session identifier

    Returns:
        Logger instance bound to the session_id

    Example:
        >>> session_logger = get_session_logger("20241130_143022")
        >>> session_logger.info("Processing request")
    """
    return logger.bind(session_id=session_id)


def set_log_level(level: str, target: str = "both") -> bool:
    """
    Change log level at runtime.

    Args:
        level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        target: "console", "file", or "both"

    Returns:
        True if successful
    """
    from merlya.utils.log_config import LogLevel, get_log_config, save_log_config

    try:
        # Validate level
        LogLevel.from_string(level)

        config = get_log_config()

        if target in ("console", "both"):
            config.console_level = level.upper()
        if target in ("file", "both"):
            config.file_level = level.upper()

        # Save and reconfigure
        save_log_config(config)
        setup_logger(config=config)
        return True
    except ValueError:
        return False


def get_log_stats() -> Dict[str, Any]:
    """
    Get logging statistics.

    Returns:
        Dict with log file info, sizes, and configuration
    """
    config = _get_log_config()
    log_dir = Path(config.log_dir)

    stats = {
        "config": {
            "log_dir": config.log_dir,
            "app_log": config.app_log_name,
            "file_level": config.file_level,
            "console_level": config.console_level,
            "rotation": config.rotation_size,
            "retention": config.retention,
        },
        "files": [],
        "total_size_bytes": 0,
        "total_size_human": "0 B",
    }

    if log_dir.exists():
        log_files = list(log_dir.glob("*.log*"))
        total_size = 0

        for log_file in sorted(log_files):
            file_stat = log_file.stat()
            size = file_stat.st_size
            total_size += size
            stats["files"].append({
                "name": log_file.name,
                "size_bytes": size,
                "size_human": _format_size(size),
                "modified": datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            })

        stats["total_size_bytes"] = total_size
        stats["total_size_human"] = _format_size(total_size)

    return stats


def _format_size(size_bytes: int) -> str:
    """Format size in bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def clear_logs(keep_current: bool = True) -> int:
    """
    Clear old log files.

    Args:
        keep_current: Keep the current log file

    Returns:
        Number of files deleted
    """
    config = _get_log_config()
    log_dir = Path(config.log_dir)
    deleted = 0

    if not log_dir.exists():
        return 0

    current_log = log_dir / config.app_log_name

    for log_file in log_dir.glob("*.log*"):
        if keep_current and log_file == current_log:
            continue
        try:
            log_file.unlink()
            deleted += 1
        except OSError:
            pass

    return deleted


def tail_log(lines: int = 50) -> str:
    """
    Get the last N lines from the current log file.

    Args:
        lines: Number of lines to return

    Returns:
        String with the last N lines
    """
    config = _get_log_config()
    log_path = Path(config.log_dir) / config.app_log_name

    if not log_path.exists():
        return ""

    try:
        with open(log_path, "r") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except OSError:
        return ""
