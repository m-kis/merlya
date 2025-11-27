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
    def redaction_filter(record):
        """Redact sensitive info from all logs."""
        record["message"] = redact_sensitive_info(record["message"])
        return True

    logger.configure(patcher=redaction_filter)

    return logger
