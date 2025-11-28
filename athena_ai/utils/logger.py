import sys
from pathlib import Path

from loguru import logger

from athena_ai.utils.security import redact_sensitive_info


def setup_logger(verbose: bool = False):
    """
    Configure the logger.

    Rules:
    1. FILE: Always log DEBUG+ to athena_ai.log (rotated).
    2. CONSOLE:
       - If verbose: Log DEBUG+ to stderr.
       - If NOT verbose: DO NOT log to stderr (DisplayManager handles UI).
    """
    logger.remove()

    # 1. File Logging (Always active, detailed)
    log_path = Path("athena_ai.log")
    logger.add(
        log_path,
        rotation="10 MB",
        retention="1 week",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
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
            return type(value)(result_list)
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

    return logger
