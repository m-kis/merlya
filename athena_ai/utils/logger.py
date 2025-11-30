import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from athena_ai.utils.security import redact_sensitive_info


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


def setup_logger(verbose: bool = False, session_id: Optional[str] = None) -> None:
    """
    Configure the logger with session-specific logging.

    Rules:
    1. FILE: Always log DEBUG+ to athena_ai.log (rotated) with session_id prefix.
    2. CONSOLE:
       - If verbose: Log DEBUG+ to stderr.
       - If NOT verbose: DO NOT log to stderr (DisplayManager handles UI).

    Args:
        verbose: Enable console logging
        session_id: Optional session ID to add to log format (for multi-instance deduplication)
    """
    logger.remove()

    # Custom format function to handle optional session_id
    def format_record(record):
        """Format log record with optional session_id."""
        # Check if session_id exists in extra, otherwise use empty string
        sid = record["extra"].get("session_id", "")
        if sid:
            return "{time:YYYY-MM-DD HH:mm:ss} | " + sid + " | {level: <8} | {name}:{function}:{line} - {message}\n"
        else:
            return "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}\n"

    # 1. File Logging (Always active, detailed)
    log_path = Path("athena_ai.log")
    logger.add(
        log_path,
        rotation="10 MB",
        retention="1 week",
        level="DEBUG",
        format=format_record,
        enqueue=True
    )

    # 2. Console Logging (Only if verbose)
    if verbose:
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level="DEBUG",
        )

    # 3. Global Redaction Filter
    def _redact_value(value, _seen=None):
        """Recursively redact sensitive info from a value."""
        if _seen is None:
            _seen = set()

        # Prevent infinite recursion on circular references
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
            # Return as list since redacted items might be unhashable
            # (e.g., a dict {"api_key": "secret"} becomes {"api_key": "[REDACTED]"})
            return result_list
        else:
            # For other types, preserve the original object to maintain type consistency
            # Sensitive data in __str__ is rare for non-string/container types
            return value

    def redaction_filter(record):
        """Redact sensitive info from all logs."""
        try:
            record["message"] = redact_sensitive_info(record["message"])
        except Exception:
            # Don't leak original data if redaction fails
            record["message"] = "[REDACTED]"

        # Redact sensitive info from extra fields
        if "extra" in record and record["extra"]:
            try:
                for key in list(record["extra"].keys()):
                    try:
                        record["extra"][key] = _redact_value(record["extra"][key])
                    except Exception:
                        # Don't leak field data if redaction fails
                        record["extra"][key] = "[REDACTED]"
            except Exception:
                # Don't leak any extra data if outer loop fails
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
        # Logs: "2024-11-30 14:30:22 | 20241130_143022 | INFO     | ... - Processing request"
    """
    return logger.bind(session_id=session_id)
