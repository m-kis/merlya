"""
Provider environment helpers.

Ensures provider-specific environment variables are set (e.g., Ollama base URL).
"""

from __future__ import annotations

import os

from loguru import logger

from merlya.config import Config


def ensure_provider_env(config: Config) -> None:
    """
    Set provider-specific environment variables if missing.

    Currently handled:
    - Ollama: sets OLLAMA_BASE_URL to config.model.base_url or default http://localhost:11434
    """
    if config.model.provider != "ollama":
        return

    env_key = "OLLAMA_BASE_URL"
    current = os.environ.get(env_key)
    if current:
        return

    base_url = config.model.base_url or "http://localhost:11434"
    os.environ[env_key] = base_url

    if not config.model.base_url:
        # Persist in memory for visibility (no disk write here)
        config.model.base_url = base_url

    logger.debug(f"🌐 {env_key} set to {base_url}")
