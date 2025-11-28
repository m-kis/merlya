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
#
# IMPORTANT: Timeout Behavior Limitation
# The timeout is enforced using ThreadPoolExecutor, which CANNOT truly cancel
# a running thread. When a timeout occurs:
# - parse_with_llm() returns immediately with an LLM_TIMEOUT error
# - The underlying LLM API call continues executing in a background thread
# - The "orphaned" thread consumes resources until the LLM call completes
# - A done-callback logs when orphaned calls complete (for monitoring)
#
# Recommendations:
# - Set timeout higher than your LLM provider's typical response time
# - If using slow models (e.g., large local models), increase to 120-300 seconds
# - Monitor logs for "Orphaned LLM call" messages indicating frequent timeouts
# - Consider using an LLM provider/client with native request cancellation support
DEFAULT_LLM_TIMEOUT = 60


def _parse_llm_timeout() -> int:
    """Safely parse LLM_TIMEOUT from environment variable."""
    env_value = os.getenv("ATHENA_LLM_TIMEOUT")
    if env_value is None:
        return DEFAULT_LLM_TIMEOUT
    try:
        timeout = int(env_value)
        if timeout <= 0:
            logger.warning(
                f"Invalid ATHENA_LLM_TIMEOUT value '{env_value}'; "
                f"must be positive. Using default: {DEFAULT_LLM_TIMEOUT}"
            )
            return DEFAULT_LLM_TIMEOUT
        return timeout
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
