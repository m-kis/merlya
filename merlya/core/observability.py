"""
Merlya Core - Anonymous product telemetry via PostHog.

Tracks anonymous feature usage to help improve the product.
No personal data, no command content, no hostnames or IPs.

Opt-out:
    MERLYA_TELEMETRY=off   (environment variable)

What is collected:
    - App version, OS, Python version
    - LLM provider name (not the key)
    - Request type (diagnostic / execution / query / security)
    - Slash command names (/hosts, /metrics, etc.)
    - Success / failure (no content)

What is NOT collected:
    - Command content, user input
    - Hostnames, IPs, server names
    - Secrets, API keys, passwords
    - Any personally identifiable information
"""

from __future__ import annotations

import os
import platform
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

# PostHog project API key — write-only, safe to embed in OSS.
# Replace with your actual key after creating a PostHog project:
#   https://posthog.com  (or EU: https://eu.posthog.com)
_POSTHOG_API_KEY = "phc_YOUR_PROJECT_API_KEY_HERE"
_POSTHOG_HOST = "https://eu.posthog.com"  # EU server (GDPR)

# Module state
_telemetry_initialized = False
_anonymous_id: str | None = None

try:
    import posthog as _posthog

    _posthog_available = True
except ImportError:
    _posthog = None  # type: ignore[assignment]
    _posthog_available = False


def _get_anonymous_id() -> str:
    """Return the persistent anonymous UUID (created once, stored locally)."""
    global _anonymous_id
    if _anonymous_id:
        return _anonymous_id

    id_file = Path.home() / ".merlya" / "telemetry_id"
    if id_file.exists():
        _anonymous_id = id_file.read_text().strip()
    else:
        _anonymous_id = str(uuid.uuid4())
        try:
            id_file.parent.mkdir(parents=True, exist_ok=True)
            id_file.write_text(_anonymous_id)
        except OSError:
            pass  # Read-only FS — use in-memory ID only

    return _anonymous_id


def is_telemetry_enabled() -> bool:
    """Check if anonymous telemetry is active."""
    return _telemetry_initialized


def init_telemetry() -> bool:
    """
    Initialize PostHog telemetry (opt-out model).

    Skipped when:
    - MERLYA_TELEMETRY=off / 0 / false / no
    - posthog package not installed
    - API key is still the placeholder value

    Returns:
        True if telemetry was activated, False otherwise.
    """
    global _telemetry_initialized

    if _telemetry_initialized:
        return True

    # Opt-out check
    opt_out = os.getenv("MERLYA_TELEMETRY", "on").lower()
    if opt_out in ("off", "0", "false", "no"):
        logger.debug("📊 Telemetry disabled (MERLYA_TELEMETRY=off)")
        return False

    if not _posthog_available or _posthog is None:
        logger.debug("📊 Telemetry skipped: posthog not installed")
        return False

    if not _POSTHOG_API_KEY or "YOUR_PROJECT_API_KEY" in _POSTHOG_API_KEY:
        logger.debug("📊 Telemetry skipped: PostHog API key not configured")
        return False

    try:
        _posthog.api_key = _POSTHOG_API_KEY
        _posthog.host = _POSTHOG_HOST
        _posthog.disabled = False
        # Silence PostHog's own logging
        _posthog.log.setLevel("CRITICAL")  # type: ignore[attr-defined]
        _telemetry_initialized = True
        logger.debug("📊 Telemetry enabled (opt-out: MERLYA_TELEMETRY=off)")
    except Exception as e:
        logger.debug(f"📊 Telemetry init failed: {e}")
        return False

    return True


def capture(event: str, properties: dict[str, Any] | None = None) -> None:
    """
    Send an anonymous telemetry event.

    Never raises — telemetry must never break the app.

    Args:
        event: Event name (e.g. "app_started", "request_completed").
        properties: Optional dict of anonymous properties.
    """
    if not _telemetry_initialized or _posthog is None:
        return

    try:
        distinct_id = _get_anonymous_id()
        _posthog.capture(distinct_id, event, properties=properties or {})  # type: ignore[misc]
    except Exception:
        pass


def capture_app_started(version: str, provider: str) -> None:
    """Fire app_started event with version and provider info."""
    capture(
        "app_started",
        {
            "version": version,
            "provider": provider,
            "os": platform.system().lower(),
            "python": platform.python_version(),
        },
    )


def capture_request(intent_type: str, provider: str, *, success: bool) -> None:
    """
    Fire request_completed event.

    Args:
        intent_type: One of "diagnostic", "execution", "security", "query".
        provider: LLM provider name (e.g. "anthropic", "openai").
        success: Whether the request completed without error.
    """
    capture(
        "request_completed",
        {
            "intent_type": intent_type,
            "provider": provider,
            "success": success,
        },
    )


def capture_command(command_name: str, *, success: bool) -> None:
    """
    Fire command_used event for slash commands.

    Args:
        command_name: Slash command name without the "/" (e.g. "hosts", "metrics").
        success: Whether the command succeeded.
    """
    capture(
        "command_used",
        {
            "command": command_name,
            "success": success,
        },
    )


def shutdown_telemetry() -> None:
    """Flush pending PostHog events and shut down gracefully."""
    global _telemetry_initialized

    if not _telemetry_initialized or _posthog is None:
        return

    try:
        _posthog.shutdown()  # type: ignore[no-untyped-call]
    except Exception:
        pass
    finally:
        _telemetry_initialized = False
