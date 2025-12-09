"""
Merlya Secrets - API key loader.

Loads API keys from keyring into environment variables.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.config import Config
    from merlya.secrets import SecretStore


def load_api_keys_from_keyring(
    config: Config,
    secrets: SecretStore,
) -> None:
    """
    Load API keys from keyring into environment variables.

    This ensures LLM providers can access API keys stored securely in keyring.
    Must be called before initializing the agent.

    Args:
        config: Application configuration.
        secrets: Secret store instance.
    """
    from merlya.config.provider_env import ollama_requires_api_key

    # Get the configured API key env variable
    api_key_env = config.model.api_key_env
    if not api_key_env:
        # Fallback to provider-based env var
        provider = config.model.provider.upper()
        api_key_env = f"{provider}_API_KEY"

    # Ollama only needs a key when using cloud endpoints
    if config.model.provider == "ollama" and not ollama_requires_api_key(config):
        logger.debug("🔑 Ollama local mode - no API key required")
        return

    # Check if already in environment
    if os.environ.get(api_key_env):
        logger.debug(f"🔑 API key already in environment: {api_key_env}")
        return

    # Try to load from keyring
    secret_value = secrets.get(api_key_env)
    if secret_value:
        os.environ[api_key_env] = secret_value
        logger.debug(f"🔑 Loaded API key from keyring: {api_key_env}")
    else:
        logger.warning(
            f"⚠️ No API key found for {api_key_env}. "
            f"Set via: export {api_key_env}=... or use /secret set {api_key_env}"
        )
