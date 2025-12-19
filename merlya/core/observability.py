"""
Merlya Core - Observability with Pydantic Logfire.

Provides distributed tracing, LLM cost tracking, and dashboard integration.
Works alongside Loguru (not replacing it) via the loguru_handler bridge.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

# Module state
_logfire_initialized = False
_logfire_available = False
_loguru_handler_id = None

# Try to import logfire
try:
    import logfire

    _logfire_available = True
except ImportError:
    logfire = None  # type: ignore[assignment]


def is_logfire_available() -> bool:
    """Check if logfire package is installed."""
    return _logfire_available


def is_logfire_enabled() -> bool:
    """Check if logfire is initialized and sending data."""
    return _logfire_initialized


def init_logfire(
    service_name: str = "merlya",
    instrument_pydantic_ai: bool = True,
    instrument_system_metrics: bool = True,
    instrument_httpx: bool = True,
    bridge_loguru: bool = True,
    loguru_level: str = "INFO",
) -> bool:
    """
    Initialize Logfire observability with full instrumentation.

    This function enables:
    1. PydanticAI instrumentation → Agent runs, tool calls, LLM costs
    2. System metrics → CPU, memory, disk usage
    3. HTTPX instrumentation → HTTP request tracing
    4. Loguru bridge → Logs sent to both local + Logfire

    Args:
        service_name: Service name in Logfire dashboard.
        instrument_pydantic_ai: Auto-instrument PydanticAI agents.
        instrument_system_metrics: Collect CPU, memory, disk metrics.
        instrument_httpx: Trace HTTP requests (LLM API calls).
        bridge_loguru: Send Loguru logs to Logfire too.
        loguru_level: Minimum level for Loguru → Logfire bridge.

    Returns:
        True if Logfire was initialized, False otherwise.

    Example:
        >>> from merlya.core.observability import init_logfire
        >>> if init_logfire():
        ...     print("Logfire enabled!")
    """
    global _logfire_initialized

    if _logfire_initialized:
        logger.debug("⚡ Logfire already initialized")
        return True

    # Check if logfire package is available
    if not _logfire_available or logfire is None:
        logger.debug("📊 Logfire package not installed, skipping")
        return False

    # Check for token
    token = os.getenv("LOGFIRE_TOKEN")
    if not token:
        logger.debug("📊 LOGFIRE_TOKEN not set, skipping Logfire")
        return False

    try:
        # Configure Logfire
        logfire.configure(
            service_name=service_name,
            send_to_logfire="if-token-present",
        )
    except Exception as e:
        logger.warning(f"⚠️ Logfire configure failed: {e}")
        return False

    enabled_features: list[str] = []

    # Instrument PydanticAI (captures all agent runs, tool calls, LLM costs)
    if instrument_pydantic_ai:
        try:
            logfire.instrument_pydantic_ai()
            enabled_features.append("PydanticAI")
        except Exception as e:
            logger.debug(f"📊 PydanticAI instrumentation skipped: {e}")

    # Instrument system metrics (CPU, memory, disk)
    if instrument_system_metrics:
        try:
            logfire.instrument_system_metrics()
            enabled_features.append("SystemMetrics")
        except Exception as e:
            logger.debug(f"📊 System metrics skipped: {e}")

    # Instrument HTTPX (traces all HTTP requests including LLM API calls)
    if instrument_httpx:
        try:
            logfire.instrument_httpx()
            enabled_features.append("HTTPX")
        except Exception as e:
            logger.debug(f"📊 HTTPX instrumentation skipped: {e}")

    # Bridge Loguru → Logfire (logs go to both places)
    if bridge_loguru:
        try:
            handler_config = logfire.loguru_handler()
            global _loguru_handler_id
            _loguru_handler_id = logger.add(
                handler_config["sink"],
                format=handler_config.get("format", "{message}"),
                level=loguru_level.upper(),
            )
            enabled_features.append("Loguru")
        except Exception as e:
            logger.debug(f"📊 Loguru bridge skipped: {e}")

    _logfire_initialized = True
    features_str = ", ".join(enabled_features) if enabled_features else "base"
    logger.info(f"📊 Logfire enabled ({features_str})")
    return True


def shutdown_logfire() -> None:
    """Shutdown Logfire gracefully (flush pending spans)."""
    global _logfire_initialized, _loguru_handler_id

    try:
        # Always remove Loguru handler if it exists
        if _loguru_handler_id is not None:
            logger.remove(_loguru_handler_id)
            _loguru_handler_id = None

        # Only proceed with logfire shutdown if it was initialized
        if _logfire_initialized and _logfire_available and logfire is not None:
            logfire.shutdown()
            _logfire_initialized = False
            logger.debug("📊 Logfire shutdown complete")
    except Exception as e:
        logger.warning(f"⚠️ Logfire shutdown error: {e}")


def get_logfire_status() -> dict[str, bool]:
    """
    Get current Logfire status.

    Returns:
        Dict with 'available', 'enabled', and 'token_present' keys.
    """
    return {
        "available": _logfire_available,
        "enabled": _logfire_initialized,
        "token_present": bool(os.getenv("LOGFIRE_TOKEN")),
    }


# Context manager for manual spans (optional, for custom tracing)
def span(name: str, **attributes: object) -> Any:
    """
    Create a Logfire span for manual tracing.

    Usage:
        >>> with span("ssh_execute", host="web-01"):
        ...     result = await execute_command()

    Args:
        name: Span name.
        **attributes: Span attributes.

    Returns:
        Context manager for the span.
    """
    if not _logfire_initialized or logfire is None:
        # Return a no-op context manager
        from contextlib import nullcontext

        return nullcontext()

    # Cast attributes to logfire's expected format
    return logfire.span(name, _attributes=attributes)
