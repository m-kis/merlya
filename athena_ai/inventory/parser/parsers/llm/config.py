"""
Configuration for LLM parser.
"""
import os
from athena_ai.utils.logger import logger

# Configuration flags for LLM fallback
ENABLE_LLM_FALLBACK = os.getenv("ATHENA_ENABLE_LLM_FALLBACK", "false").lower() == "true"
LLM_COMPLIANCE_ACKNOWLEDGED = os.getenv("ATHENA_LLM_COMPLIANCE_ACKNOWLEDGED", "false").lower() == "true"

# Default timeout for LLM generate calls (in seconds)
# Can be overridden via ATHENA_LLM_TIMEOUT environment variable
DEFAULT_LLM_TIMEOUT = 60


def _parse_llm_timeout() -> int:
    """Safely parse LLM_TIMEOUT from environment variable."""
    env_value = os.getenv("ATHENA_LLM_TIMEOUT")
    if env_value is None:
        return DEFAULT_LLM_TIMEOUT
    try:
        return int(env_value)
    except ValueError:
        logger.warning(
            f"Invalid ATHENA_LLM_TIMEOUT value '{env_value}'; "
            f"must be an integer. Using default: {DEFAULT_LLM_TIMEOUT}"
        )
        return DEFAULT_LLM_TIMEOUT


LLM_TIMEOUT = _parse_llm_timeout()

# Strict delimiters for content embedding - random-ish to prevent confusion
CONTENT_START_DELIMITER = "<<<INVENTORY_CONTENT_BEGIN_7f3a9b2e>>>"
CONTENT_END_DELIMITER = "<<<INVENTORY_CONTENT_END_7f3a9b2e>>>"
