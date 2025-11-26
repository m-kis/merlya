"""
Model configuration management for flexible LLM routing.
KISS approach: Simple JSON config with runtime overrides.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from athena_ai.utils.logger import logger


class ModelConfig:
    """
    Manages model configuration across providers.
    Supports: OpenRouter, Anthropic, OpenAI, Ollama
    """

    # Available models per provider (suggestions - NOT exhaustive)
    # Note: OpenRouter supports 400+ models - this is just a curated list
    # You can use ANY model from https://openrouter.ai/models
    AVAILABLE_MODELS = {
        "openrouter": [
            # Claude 4.x (latest generation - premium)
            "anthropic/claude-4.5-sonnet-20250929",
            "anthropic/claude-4.5-haiku-20251001",
            "anthropic/claude-4.1-opus-20250805",
            "anthropic/claude-4-sonnet-20250522",
            "anthropic/claude-4-opus-20250522",
            # Claude 3.7
            "anthropic/claude-3-7-sonnet-20250219",
            # Claude 3.5 (stable)
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3.5-sonnet-20240620",
            "anthropic/claude-3-5-haiku",
            # Claude 3 (legacy)
            "anthropic/claude-3-opus",
            "anthropic/claude-3-haiku",
            # OpenAI GPT-4o (latest)
            "openai/gpt-4o",
            "openai/gpt-4o-2024-11-20",
            "openai/gpt-4o-2024-08-06",
            "openai/gpt-4o-mini",
            # OpenAI GPT-4 (stable)
            "openai/gpt-4-turbo",
            "openai/gpt-4",
            "openai/gpt-3.5-turbo",
            # Free models
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "meta-llama/llama-3.2-90b-vision-instruct:free",
            "google/gemini-flash-1.5:free",
            "qwen/qwen-2-7b-instruct:free",
            "microsoft/phi-3-mini-128k-instruct:free",
            # Other popular models
            "meta-llama/llama-3-70b-instruct",
            "google/gemini-pro-1.5",
            "mistralai/mixtral-8x7b-instruct",
            "deepseek/deepseek-chat",
            # Example: You can use ANY model like "z-ai/glm-4.5-air:free"
        ],
        "anthropic": [
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
        ],
        "openai": [
            "gpt-4o",
            "gpt-4o-2024-11-20",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ],
        "ollama": [
            "llama3",
            "mistral",
            "codellama",
            "deepseek-coder",
        ],
    }

    # Default models per provider (latest stable versions)
    DEFAULT_MODELS = {
        "openrouter": "anthropic/claude-4.5-sonnet-20250929",  # Claude 4.5 Sonnet (latest)
        "anthropic": "claude-3-5-sonnet-20241022",
        "openai": "gpt-4o",  # GPT-4o (latest)
        "ollama": "llama3",
    }

    # Task-specific model preferences (optimized for speed vs quality)
    TASK_MODELS = {
        "correction": "haiku",  # Fast corrections (haiku = fastest)
        "planning": "opus",     # Complex planning (opus = most capable)
        "synthesis": "sonnet",  # Balanced synthesis (sonnet = balanced)
    }

    def __init__(self):
        self.config_dir = Path.home() / ".athena"
        self.config_file = self.config_dir / "config.json"
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load configuration from file or create default."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")

        # Default config
        return {
            "provider": "openrouter",
            "models": self.DEFAULT_MODELS.copy(),
            "task_models": self.TASK_MODELS.copy(),
        }

    def save_config(self):
        """Save current configuration to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, indent=2, fp=f)
            logger.debug(f"Config saved to {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def get_provider(self) -> str:
        """Get current provider."""
        return self.config.get("provider", "openrouter")

    def set_provider(self, provider: str):
        """Set provider (openrouter, anthropic, openai, ollama)."""
        if provider not in self.AVAILABLE_MODELS:
            raise ValueError(f"Unknown provider: {provider}")

        self.config["provider"] = provider
        self.save_config()
        logger.info(f"Provider set to: {provider}")

    def get_model(self, provider: Optional[str] = None, task: Optional[str] = None) -> str:
        """
        Get model for provider and optional task.

        Args:
            provider: Provider name (uses current if None)
            task: Task type (correction, planning, synthesis)

        Returns:
            Model identifier
        """
        provider = provider or self.get_provider()

        # Get configured model
        models = self.config.get("models", {})
        configured_model = models.get(provider, self.DEFAULT_MODELS.get(provider, ""))

        # NEW: Task-specific model override - works with ANY model!
        if task and task in self.config.get("task_models", {}):
            task_model = self.config["task_models"][task]

            # Check if it's an alias (haiku, sonnet, opus, fast, balanced, best)
            # OR a full model path (like qwen/qwen-2.5-coder-7b-instruct)
            if "/" in task_model:
                # It's a full model path - use it directly
                return task_model
            else:
                # It's an alias - resolve it based on provider
                return self._resolve_model_alias(provider, task_model)

        # Return configured model (custom or default)
        return configured_model

    def set_model(self, provider: str, model: str):
        """
        Set default model for a provider.

        For OpenRouter: accepts ANY model ID (e.g., z-ai/glm-4.5-air:free)
        For other providers: validates against known models
        """
        if provider not in self.AVAILABLE_MODELS:
            raise ValueError(f"Unknown provider: {provider}. Available: {', '.join(self.AVAILABLE_MODELS.keys())}")

        # For OpenRouter, accept any model without validation (it's a gateway)
        # For other providers, warn if model not in known list but still allow it
        if provider != "openrouter" and model not in self.AVAILABLE_MODELS.get(provider, []):
            logger.warning(f"Model '{model}' not in known {provider} models list. Setting anyway.")

        if "models" not in self.config:
            self.config["models"] = {}

        self.config["models"][provider] = model
        self.save_config()
        logger.info(f"Model for {provider} set to: {model}")

    def list_models(self, provider: Optional[str] = None) -> List[str]:
        """List available models for provider."""
        provider = provider or self.get_provider()
        return self.AVAILABLE_MODELS.get(provider, [])

    def _resolve_model_alias(self, provider: str, alias: str) -> str:
        """
        Resolve model alias (haiku, opus, sonnet) to actual model.

        Examples (OpenRouter):
        - haiku → anthropic/claude-4.5-haiku-20251001 (fastest, cheapest)
        - sonnet → anthropic/claude-4.5-sonnet-20250929 (balanced)
        - opus → anthropic/claude-4.1-opus-20250805 (most capable)
        """
        alias_map = {
            "openrouter": {
                # Use Claude 3.5 models (verified to work on OpenRouter)
                "haiku": "anthropic/claude-3-5-haiku",               # Fastest
                "sonnet": "anthropic/claude-3.5-sonnet",             # Balanced
                "opus": "anthropic/claude-3-opus",                   # Most capable (Claude 3)
                # Legacy aliases
                "haiku-3": "anthropic/claude-3-haiku",
                "sonnet-3.5": "anthropic/claude-3.5-sonnet",
                "opus-3": "anthropic/claude-3-opus",
            },
            "anthropic": {
                "haiku": "claude-3-haiku-20240307",
                "sonnet": "claude-3-5-sonnet-20241022",
                "opus": "claude-3-opus-20240229",
            },
            "openai": {
                "fast": "gpt-4o-mini",           # Fastest, cheapest
                "balanced": "gpt-4o",            # Best balance
                "best": "gpt-4o-2024-11-20",     # Latest version
                # Legacy
                "gpt4": "gpt-4-turbo",
            },
            "ollama": {
                "fast": "mistral",
                "balanced": "llama3",
                "best": "deepseek-coder",
            },
        }

        provider_aliases = alias_map.get(provider, {})
        resolved = provider_aliases.get(alias, alias)

        return resolved

    def set_task_model(self, task: str, model: str):
        """
        Set model for a specific task.

        Args:
            task: Task type (correction, planning, synthesis)
            model: Model alias (haiku, sonnet, opus, fast, balanced, best)
                   OR full model path (e.g., qwen/qwen-2.5-coder-7b-instruct)

        Raises:
            ValueError: If task is invalid

        Examples:
            >>> config.set_task_model("correction", "haiku")  # Alias
            >>> config.set_task_model("planning", "qwen/qwen3-coder-30b-a3b-instruct")  # Full path
            >>> config.set_task_model("synthesis", "meta-llama/llama-3.1-70b-instruct")  # Any model!
        """
        valid_tasks = ["correction", "planning", "synthesis"]
        if task not in valid_tasks:
            raise ValueError(f"Invalid task: {task}. Must be one of: {', '.join(valid_tasks)}")

        if "task_models" not in self.config:
            self.config["task_models"] = {}

        self.config["task_models"][task] = model
        self.save_config()
        logger.info(f"Task model for {task} set to: {model}")

    def get_task_models(self) -> Dict[str, str]:
        """Get all task model configurations."""
        return self.config.get("task_models", {})

    def get_current_config(self) -> Dict:
        """Get current configuration for display."""
        provider = self.get_provider()
        model = self.get_model(provider)

        return {
            "provider": provider,
            "model": model,
            "task_models": self.config.get("task_models", {}),
        }
