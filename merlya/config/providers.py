"""
Merlya Config - Provider model defaults.

Defines intelligent defaults for LLM models per provider.
Each provider has two model roles:
  - brain: Complex reasoning, planning, analysis (Orchestrator, Centers)
  - fast: Quick routing, fingerprinting, token-efficient tasks (Router, Classifier)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loguru import logger

# Supported providers
ProviderName = Literal[
    "openrouter",
    "mistral",
    "anthropic",
    "openai",
    "groq",
    "ollama",
    "google",
]

# Model roles
ModelRole = Literal["brain", "fast"]


@dataclass(frozen=True)
class ProviderModels:
    """Model identifiers for a provider.

    Attributes:
        brain: Model for complex reasoning (orchestrator, centers, planning).
        fast: Model for quick tasks (routing, fingerprinting, classification).
        api_key_env: Environment variable name for API key.
        base_url: Optional base URL (for self-hosted providers like Ollama).
    """

    brain: str
    fast: str
    api_key_env: str | None = None
    base_url: str | None = None

    # Backward compatibility alias
    @property
    def reasoning(self) -> str:
        """Alias for brain (backward compatibility)."""
        return self.brain


# Default models per provider (2025 Q1)
# User can override via wizard or config set
PROVIDER_DEFAULTS: dict[str, ProviderModels] = {
    # OpenRouter - Free tier focus
    "openrouter": ProviderModels(
        brain="z-ai/glm-4.6",
        fast="mistralai/mistral-small-3.1-24b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
    ),
    # Mistral AI - Devstral for brain tasks
    "mistral": ProviderModels(
        brain="devstral-2512",
        fast="ministral-8b-2410",
        api_key_env="MISTRAL_API_KEY",
    ),
    # Anthropic - Claude 4.5 family
    "anthropic": ProviderModels(
        brain="claude-sonnet-4-5-20250514",
        fast="claude-haiku-4-5-20250514",
        api_key_env="ANTHROPIC_API_KEY",
    ),
    # OpenAI - GPT-4.1 family
    "openai": ProviderModels(
        brain="gpt-4.1",
        fast="gpt-4.1-mini",
        api_key_env="OPENAI_API_KEY",
    ),
    # Groq - Fast inference
    "groq": ProviderModels(
        brain="llama-3.3-70b-versatile",
        fast="llama-3.1-8b-instant",
        api_key_env="GROQ_API_KEY",
    ),
    # Ollama - Local models
    "ollama": ProviderModels(
        brain="qwen2.5:32b",
        fast="mistral:7b",
        api_key_env=None,
        base_url="http://localhost:11434/v1",
    ),
    # Google - Gemini family
    "google": ProviderModels(
        brain="gemini-2.0-flash",
        fast="gemini-2.0-flash-lite",
        api_key_env="GOOGLE_API_KEY",
    ),
}


def get_provider_models(provider: str) -> ProviderModels:
    """
    Get model defaults for a provider.

    Args:
        provider: Provider name (openrouter, mistral, anthropic, etc.).

    Returns:
        ProviderModels with reasoning and fast model identifiers.

    Raises:
        ValueError: If provider is not supported.
    """
    provider_lower = provider.lower()

    if provider_lower not in PROVIDER_DEFAULTS:
        supported = ", ".join(sorted(PROVIDER_DEFAULTS.keys()))
        raise ValueError(f"❌ Unknown provider '{provider}'. Supported: {supported}")

    return PROVIDER_DEFAULTS[provider_lower]


def get_model_for_role(
    provider: str,
    role: ModelRole | Literal["reasoning"],
    override: str | None = None,
) -> str:
    """
    Get model identifier for a specific role.

    Args:
        provider: Provider name.
        role: Model role - "brain" or "fast" (or "reasoning" for backward compat).
        override: Optional override model (takes precedence).

    Returns:
        Model identifier string.
    """
    if override:
        logger.debug(f"📋 Using override model: {override}")
        return override

    models = get_provider_models(provider)

    # Map role to model (with backward compatibility)
    model = models.brain if role in ("brain", "reasoning") else models.fast

    logger.debug(f"📋 Using {role} model for {provider}: {model}")
    return model


def get_pydantic_model_string(provider: str, model: str) -> str:
    """
    Build the pydantic-ai model string.

    PydanticAI uses format: "provider:model" for most providers.

    Args:
        provider: Provider name.
        model: Model identifier.

    Returns:
        Model string for pydantic-ai (e.g., "openai:gpt-4.1").
    """
    provider_lower = provider.lower()

    # OpenRouter uses openai-compatible endpoint
    if provider_lower == "openrouter":
        return f"openai:{model}"

    # Groq uses native groq: endpoint
    if provider_lower == "groq":
        return f"groq:{model}"

    # Ollama uses openai-compatible endpoint
    if provider_lower == "ollama":
        return f"openai:{model}"

    # Standard providers
    return f"{provider_lower}:{model}"


def list_providers() -> list[str]:
    """
    List all supported providers.

    Returns:
        Sorted list of provider names.
    """
    return sorted(PROVIDER_DEFAULTS.keys())


def get_provider_info(provider: str) -> dict[str, str | None]:
    """
    Get provider information for display.

    Args:
        provider: Provider name.

    Returns:
        Dict with provider details.
    """
    models = get_provider_models(provider)
    return {
        "provider": provider,
        "brain_model": models.brain,
        "fast_model": models.fast,
        "api_key_env": models.api_key_env,
        "base_url": models.base_url,
    }
