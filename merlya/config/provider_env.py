"""
Provider environment helpers.

Ensures provider-specific environment variables are set (e.g., Ollama base URL).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.config import Config


def ensure_provider_env(config: Config) -> None:
    """
    Set provider-specific environment variables if missing.

    Currently handled:
    - Ollama: sets OLLAMA_BASE_URL to config.model.base_url or default http://localhost:11434/v1
    - OpenRouter: sets OPENAI_API_KEY and OPENAI_BASE_URL for PydanticAI compatibility
    """
    provider = config.model.provider.lower() if config.model.provider else ""

    if provider == "openrouter":
        _ensure_openrouter_env(config)
        return

    if provider != "ollama":
        return

    env_key = "OLLAMA_BASE_URL"
    host_key = "OLLAMA_HOST"
    env_override = os.environ.get(env_key) or os.environ.get(host_key)
    is_cloud_model = "cloud" in (config.model.model or "").lower()

    # If model is cloud but env override points to localhost, ignore override
    if env_override and is_cloud_model and "localhost" in env_override:
        env_override = None

    # Priority 1: explicit environment override from user
    if env_override:
        base_url = _normalize_ollama_base(env_override)
        os.environ[env_key] = base_url
        os.environ[host_key] = base_url
        config.model.base_url = base_url
        logger.debug(f"🌐 {env_key} set from environment override: {base_url}")
        return

    is_cloud = is_cloud_model or ollama_requires_api_key(config)
    default_base = "https://ollama.com" if is_cloud else "http://localhost:11434"
    base_url = _normalize_ollama_base(config.model.base_url or default_base)

    os.environ[env_key] = base_url
    os.environ[host_key] = base_url
    config.model.base_url = base_url

    logger.debug(f"🌐 {env_key} set to {base_url}")


def ollama_requires_api_key(config: Config) -> bool:
    """
    Determine if Ollama should use an API key.

    Heuristics:
    - model name contains "cloud"
    - base_url not pointing to localhost/127.0.0.1
    """
    if config.model.provider != "ollama":
        return False

    model = (config.model.model or "").lower()
    if "cloud" in model:
        return True

    base_url = (config.model.base_url or "").lower()
    if not base_url:
        return False

    return not (
        base_url.startswith("http://localhost")
        or base_url.startswith("https://localhost")
        or base_url.startswith("http://127.0.0.1")
        or base_url.startswith("https://127.0.0.1")
    )


def ensure_openrouter_headers() -> None:
    """
    Ensure recommended OpenRouter headers are present.

    OpenRouter suggests setting HTTP_REFERER and X-Title for attribution.
    """
    if not os.getenv("HTTP_REFERER"):
        os.environ["HTTP_REFERER"] = "https://merlya.local"
    if not os.getenv("X_TITLE"):
        os.environ["X_TITLE"] = "Merlya"


def _ensure_openrouter_env(config: Config) -> None:
    """
    Set OpenRouter environment for PydanticAI compatibility.

    OpenRouter uses OpenAI-compatible API, so PydanticAI uses openai:model format.
    We need to:
    1. Set OPENAI_BASE_URL to OpenRouter's endpoint
    2. Copy OPENROUTER_API_KEY to OPENAI_API_KEY (if not already set)

    Priority:
    - OPENAI_API_KEY: Use existing if set, otherwise use OPENROUTER_API_KEY
    - OPENAI_BASE_URL: Always set to OpenRouter endpoint
    """
    from merlya.secrets import get_secret_store

    openrouter_base = "https://openrouter.ai/api/v1"

    # Set base URL (always override for OpenRouter)
    os.environ["OPENAI_BASE_URL"] = openrouter_base
    config.model.base_url = openrouter_base
    logger.debug(f"🌐 OPENAI_BASE_URL set to {openrouter_base}")

    # Get API key - priority: OPENAI_API_KEY > OPENROUTER_API_KEY > keyring
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        # Try OPENROUTER_API_KEY env var
        api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        # Try keyring
        try:
            secrets = get_secret_store()
            api_key = secrets.get("OPENROUTER_API_KEY")
        except Exception:
            pass

    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        logger.debug("🔑 OPENAI_API_KEY set from OpenRouter API key")
    else:
        logger.warning(
            "⚠️ No OpenRouter API key found. Set OPENROUTER_API_KEY or use /secret set OPENROUTER_API_KEY"
        )

    # Also set recommended headers
    ensure_openrouter_headers()


def _normalize_ollama_base(base: str) -> str:
    """Normalize Ollama base URL with host migration and /v1 suffix."""
    base_url = base or ""
    # Migrate legacy host
    if "api.ollama.ai" in base_url:
        base_url = base_url.replace("api.ollama.ai", "ollama.com")
    # Ensure scheme present
    if base_url.startswith("ollama.com"):
        base_url = f"https://{base_url}"
    # Append /v1
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return base_url
