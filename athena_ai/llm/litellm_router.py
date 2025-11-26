"""
LiteLLM Router for AutoGen multi-agent system.
Adapts existing LLMRouter configuration to work with AutoGen agents.

This preserves multi-provider flexibility (OpenRouter, Anthropic, OpenAI, Ollama)
while enabling agent behavior through AutoGen.
"""
import os
from typing import NamedTuple
from athena_ai.llm.model_config import ModelConfig
from athena_ai.utils.logger import logger


class ModelInfo(NamedTuple):
    """Simple model information container (no dependency on external SDKs)."""
    model: str  # Model name/ID
    api_key: str  # API key for the provider


class LiteLLMRouter:
    """
    Wrapper that adapts LLMRouter configuration for AutoGen agents.

    Preserves the existing multi-provider configuration system while enabling
    agent tool-calling behavior through AutoGen.

    Features:
    - Uses existing ModelConfig for provider/model selection
    - Supports task-specific routing (correction, planning, synthesis)
    - Works with OpenRouter, Anthropic, OpenAI, Ollama
    - Automatic model ID formatting for each provider
    """

    def __init__(self):
        self.model_config = ModelConfig()
        self.provider = self.model_config.get_provider()
        logger.debug(f"LiteLLMRouter initialized with provider: {self.provider}")

    def get_model(self, task: str = None) -> ModelInfo:
        """
        Get model configuration for the current provider.

        Args:
            task: Optional task type for model routing (correction, planning, synthesis)

        Returns:
            ModelInfo with model name and API key

        Examples:
            >>> router = LiteLLMRouter()
            >>> model = router.get_model()  # Uses default model
            >>> model = router.get_model(task="correction")  # Uses fast model for corrections
        """
        # Get model from existing config (respects task-specific routing)
        model_id = self.model_config.get_model(self.provider, task=task)

        # Get API key based on provider
        api_key = self._get_api_key(self.provider)

        # Format model ID according to LiteLLM conventions
        formatted_model_id = self._format_model_id(model_id, self.provider)

        # Set provider-specific environment variables
        self._set_provider_env(self.provider)

        logger.debug(f"Model config: {formatted_model_id} (provider: {self.provider}, task: {task})")

        return ModelInfo(model=formatted_model_id, api_key=api_key)

    def _format_model_id(self, model_id: str, provider: str) -> str:
        """
        Format model ID according to LiteLLM conventions.

        LiteLLM expects provider-prefixed model IDs:
        - OpenRouter: "openrouter/anthropic/claude-4.5-sonnet"
        - Anthropic: "anthropic/claude-3-5-sonnet"
        - OpenAI: "gpt-4o" or "openai/gpt-4o"
        - Ollama: "ollama/llama3"

        Args:
            model_id: Model ID from ModelConfig
            provider: Provider name

        Returns:
            Formatted model ID for LiteLLM
        """
        if provider == "openrouter":
            # OpenRouter requires "openrouter/" prefix + model path
            if not model_id.startswith("openrouter/"):
                # If model already has provider prefix (e.g., "anthropic/claude-..."), keep it
                if "/" in model_id:
                    model_id = f"openrouter/{model_id}"
                else:
                    # Otherwise, assume it's a full model path
                    model_id = f"openrouter/{model_id}"

        elif provider == "anthropic":
            # Anthropic can work with or without prefix
            if not model_id.startswith("anthropic/") and "/" not in model_id:
                # Only add prefix if it's a bare model name
                model_id = f"anthropic/{model_id}"

        elif provider == "ollama":
            # Ollama requires "ollama/" prefix
            if not model_id.startswith("ollama/") and not model_id.startswith("ollama_chat/"):
                model_id = f"ollama/{model_id}"

        elif provider == "openai":
            # OpenAI models work with or without prefix
            # LiteLLM accepts both "gpt-4o" and "openai/gpt-4o"
            pass

        return model_id

    def _get_api_key(self, provider: str) -> str:
        """
        Get API key for provider from environment variables.

        Args:
            provider: Provider name (openrouter, anthropic, openai, ollama)

        Returns:
            API key string (empty if not found or not needed)
        """
        key_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "ollama": "OLLAMA_API_KEY",  # Not required but kept for consistency
        }

        env_var = key_map.get(provider, "")
        api_key = os.getenv(env_var, "")

        if not api_key and provider != "ollama":
            logger.warning(f"API key not found for {provider}. Set {env_var} environment variable.")

        # Ollama doesn't require a real API key
        if provider == "ollama" and not api_key:
            api_key = "ollama"

        return api_key

    def _set_provider_env(self, provider: str):
        """
        Set provider-specific environment variables required by LiteLLM.

        Args:
            provider: Provider name
        """
        if provider == "ollama":
            # Set Ollama API base if not already set
            if "OLLAMA_API_BASE" not in os.environ:
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                os.environ["OLLAMA_API_BASE"] = ollama_host
                logger.debug(f"Set OLLAMA_API_BASE to {ollama_host}")

    def switch_provider(self, provider: str):
        """
        Dynamically switch to a different provider.

        Args:
            provider: New provider name (openrouter, anthropic, openai, ollama)

        Raises:
            ValueError: If provider is not supported
        """
        valid_providers = ["openrouter", "anthropic", "openai", "ollama"]
        if provider not in valid_providers:
            raise ValueError(f"Invalid provider: {provider}. Must be one of: {valid_providers}")

        self.provider = provider
        self.model_config.config["provider"] = provider
        self.model_config.save_config()
        logger.info(f"Switched to provider: {provider}")

    def get_available_providers(self) -> list:
        """Get list of available providers."""
        return ["openrouter", "anthropic", "openai", "ollama"]
