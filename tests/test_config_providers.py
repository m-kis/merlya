"""
Tests for merlya.config.providers module.
"""

import pytest

from merlya.config import LLMConfig
from merlya.config.providers import (
    PROVIDER_DEFAULTS,
    get_model_for_role,
    get_provider_info,
    get_provider_models,
    get_pydantic_model_string,
    list_providers,
)


class TestProviderDefaults:
    """Tests for provider default configurations."""

    def test_all_providers_have_required_fields(self) -> None:
        """Each provider should have reasoning and fast models."""
        for provider, models in PROVIDER_DEFAULTS.items():
            assert models.reasoning, f"❌ {provider} missing reasoning model"
            assert models.fast, f"❌ {provider} missing fast model"

    def test_openrouter_defaults(self) -> None:
        """OpenRouter should have user-specified defaults."""
        models = get_provider_models("openrouter")
        assert models.reasoning == "z-ai/glm-4.6"
        assert models.fast == "mistralai/mistral-small-3.1-24b-instruct:free"
        assert models.api_key_env == "OPENROUTER_API_KEY"

    def test_mistral_defaults(self) -> None:
        """Mistral should have devstral for reasoning."""
        models = get_provider_models("mistral")
        assert "devstral" in models.reasoning
        assert models.api_key_env == "MISTRAL_API_KEY"

    def test_anthropic_defaults(self) -> None:
        """Anthropic should have Claude 4.5 family."""
        models = get_provider_models("anthropic")
        assert "claude-sonnet" in models.reasoning or "sonnet" in models.reasoning
        assert "claude-haiku" in models.fast or "haiku" in models.fast

    def test_ollama_has_base_url(self) -> None:
        """Ollama should have local base URL."""
        models = get_provider_models("ollama")
        assert models.base_url is not None
        assert "localhost" in models.base_url
        assert models.api_key_env is None  # No API key needed


class TestGetProviderModels:
    """Tests for get_provider_models function."""

    def test_case_insensitive(self) -> None:
        """Provider name should be case-insensitive."""
        m1 = get_provider_models("openrouter")
        m2 = get_provider_models("OPENROUTER")
        m3 = get_provider_models("OpenRouter")
        assert m1 == m2 == m3

    def test_unknown_provider_raises(self) -> None:
        """Unknown provider should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_models("unknown_provider")


class TestGetModelForRole:
    """Tests for get_model_for_role function."""

    def test_returns_reasoning_model(self) -> None:
        """Should return reasoning model for 'reasoning' role."""
        model = get_model_for_role("openrouter", "reasoning")
        assert model == "z-ai/glm-4.6"

    def test_returns_fast_model(self) -> None:
        """Should return fast model for 'fast' role."""
        model = get_model_for_role("openrouter", "fast")
        assert model == "mistralai/mistral-small-3.1-24b-instruct:free"

    def test_override_takes_precedence(self) -> None:
        """Override should take precedence over default."""
        model = get_model_for_role("openrouter", "reasoning", "custom/model")
        assert model == "custom/model"


class TestGetPydanticModelString:
    """Tests for get_pydantic_model_string function."""

    def test_openai_format(self) -> None:
        """OpenAI should use provider:model format."""
        result = get_pydantic_model_string("openai", "gpt-4.1")
        assert result == "openai:gpt-4.1"

    def test_anthropic_format(self) -> None:
        """Anthropic should use provider:model format."""
        result = get_pydantic_model_string("anthropic", "claude-sonnet-4-5")
        assert result == "anthropic:claude-sonnet-4-5"

    def test_openrouter_uses_openai_prefix(self) -> None:
        """OpenRouter uses openai-compatible endpoint."""
        result = get_pydantic_model_string("openrouter", "z-ai/glm-4.6")
        assert result == "openai:z-ai/glm-4.6"

    def test_groq_uses_groq_prefix(self) -> None:
        """Groq uses its own prefix."""
        result = get_pydantic_model_string("groq", "llama-3.3-70b")
        assert result == "groq:llama-3.3-70b"

    def test_ollama_uses_openai_prefix(self) -> None:
        """Ollama uses openai-compatible endpoint."""
        result = get_pydantic_model_string("ollama", "qwen2.5:32b")
        assert result == "openai:qwen2.5:32b"


class TestListProviders:
    """Tests for list_providers function."""

    def test_returns_sorted_list(self) -> None:
        """Should return sorted list of providers."""
        providers = list_providers()
        assert providers == sorted(providers)
        assert len(providers) >= 6  # At least 6 providers

    def test_contains_expected_providers(self) -> None:
        """Should contain main providers."""
        providers = list_providers()
        assert "openrouter" in providers
        assert "anthropic" in providers
        assert "openai" in providers
        assert "ollama" in providers


class TestGetProviderInfo:
    """Tests for get_provider_info function."""

    def test_returns_dict_with_all_fields(self) -> None:
        """Should return dict with all info fields."""
        info = get_provider_info("openrouter")
        assert "provider" in info
        assert "brain_model" in info
        assert "fast_model" in info
        assert "api_key_env" in info
        assert info["provider"] == "openrouter"


class TestLLMConfigIntegration:
    """Tests for LLMConfig methods that use providers."""

    def test_get_orchestrator_model_default(self) -> None:
        """Should return default model when no override."""
        cfg = LLMConfig()
        assert cfg.get_orchestrator_model() == "z-ai/glm-4.6"

    def test_get_orchestrator_model_with_override(self) -> None:
        """Should return override when set."""
        cfg = LLMConfig(reasoning_model="custom/model")
        assert cfg.get_orchestrator_model() == "custom/model"

    def test_get_reasoning_model(self) -> None:
        """Should get reasoning model from provider defaults."""
        cfg = LLMConfig(provider="anthropic")
        model = cfg.get_reasoning_model()
        assert "claude" in model.lower() or "sonnet" in model.lower()

    def test_get_fast_model(self) -> None:
        """Should get fast model from provider defaults."""
        cfg = LLMConfig(provider="anthropic")
        model = cfg.get_fast_model()
        assert "claude" in model.lower() or "haiku" in model.lower()

    def test_model_override_respected(self) -> None:
        """Override in config should be respected."""
        cfg = LLMConfig(
            provider="openrouter",
            reasoning_model="override/reasoning",
            fast_model="override/fast",
        )
        assert cfg.get_reasoning_model() == "override/reasoning"
        assert cfg.get_fast_model() == "override/fast"
