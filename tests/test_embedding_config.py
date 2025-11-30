"""
Tests for Embedding Model Configuration.

Tests the centralized embedding model configuration system.
"""

import os

import pytest

from athena_ai.triage.embedding_config import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    ENV_VAR_MODEL,
    EmbeddingConfig,
    EmbeddingModelInfo,
    get_current_embedding_model,
    get_embedding_config,
)


@pytest.fixture(autouse=True)
def reset_embedding_config():
    """Reset singleton between tests."""
    EmbeddingConfig.reset_instance()
    # Clean up env var
    if ENV_VAR_MODEL in os.environ:
        del os.environ[ENV_VAR_MODEL]
    yield
    EmbeddingConfig.reset_instance()
    if ENV_VAR_MODEL in os.environ:
        del os.environ[ENV_VAR_MODEL]


class TestAvailableModels:
    """Tests for available embedding models."""

    def test_available_models_not_empty(self):
        """AVAILABLE_MODELS should contain models."""
        assert len(AVAILABLE_MODELS) > 0

    def test_default_model_exists(self):
        """DEFAULT_MODEL should be in AVAILABLE_MODELS."""
        assert DEFAULT_MODEL in AVAILABLE_MODELS

    def test_model_info_has_required_fields(self):
        """Each model should have required fields."""
        for name, info in AVAILABLE_MODELS.items():
            assert isinstance(info, EmbeddingModelInfo)
            assert info.name == name
            assert isinstance(info.size_mb, int)
            assert info.size_mb > 0
            assert isinstance(info.dimensions, int)
            assert info.dimensions > 0
            assert info.speed in ("fast", "medium", "slow")
            assert info.quality in ("good", "better", "best")
            assert len(info.description) > 0

    def test_bge_small_is_default(self):
        """BGE small should be the default model."""
        assert DEFAULT_MODEL == "BAAI/bge-small-en-v1.5"

    def test_bge_models_present(self):
        """BGE models should be available."""
        assert "BAAI/bge-small-en-v1.5" in AVAILABLE_MODELS
        assert "BAAI/bge-base-en-v1.5" in AVAILABLE_MODELS

    def test_e5_models_present(self):
        """E5 models should be available."""
        assert "intfloat/e5-small-v2" in AVAILABLE_MODELS
        assert "intfloat/e5-base-v2" in AVAILABLE_MODELS

    def test_gte_models_present(self):
        """GTE models should be available."""
        assert "thenlper/gte-small" in AVAILABLE_MODELS
        assert "thenlper/gte-base" in AVAILABLE_MODELS

    def test_minilm_models_present(self):
        """MiniLM models should be available."""
        assert "all-MiniLM-L6-v2" in AVAILABLE_MODELS

    def test_model_dimensions_correct(self):
        """Model dimensions should match expected values."""
        # Small models have 384 dimensions
        small_models = [
            "BAAI/bge-small-en-v1.5",
            "intfloat/e5-small-v2",
            "thenlper/gte-small",
            "all-MiniLM-L6-v2",
        ]
        for model in small_models:
            assert AVAILABLE_MODELS[model].dimensions == 384, f"{model} should have 384 dims"

        # Base models have 768 dimensions
        base_models = [
            "BAAI/bge-base-en-v1.5",
            "intfloat/e5-base-v2",
            "thenlper/gte-base",
        ]
        for model in base_models:
            assert AVAILABLE_MODELS[model].dimensions == 768, f"{model} should have 768 dims"


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig class."""

    def test_singleton_pattern(self):
        """EmbeddingConfig should be a singleton."""
        config1 = EmbeddingConfig()
        config2 = EmbeddingConfig()
        assert config1 is config2

    def test_default_model_used(self):
        """Should use default model when no env var set."""
        config = EmbeddingConfig()
        assert config.current_model == DEFAULT_MODEL

    def test_env_var_override(self):
        """Should use env var model when set."""
        os.environ[ENV_VAR_MODEL] = "all-MiniLM-L6-v2"
        EmbeddingConfig.reset_instance()
        config = EmbeddingConfig()
        assert config.current_model == "all-MiniLM-L6-v2"

    def test_invalid_env_var_fallback(self):
        """Should fall back to default for invalid env var."""
        os.environ[ENV_VAR_MODEL] = "invalid-model-name"
        EmbeddingConfig.reset_instance()
        config = EmbeddingConfig()
        assert config.current_model == DEFAULT_MODEL

    def test_set_model_valid(self):
        """set_model should work for valid models."""
        config = EmbeddingConfig()
        assert config.set_model("all-MiniLM-L6-v2") is True
        assert config.current_model == "all-MiniLM-L6-v2"

    def test_set_model_custom(self):
        """set_model should accept custom models not in AVAILABLE_MODELS."""
        config = EmbeddingConfig()
        # Custom models are now allowed
        assert config.set_model("google/gemma-2b") is True
        assert config.current_model == "google/gemma-2b"

    def test_set_model_same(self):
        """set_model should return True for same model."""
        config = EmbeddingConfig()
        assert config.set_model(DEFAULT_MODEL) is True
        assert config.current_model == DEFAULT_MODEL

    def test_set_model_updates_env(self):
        """set_model should update environment variable."""
        config = EmbeddingConfig()
        config.set_model("all-MiniLM-L6-v2")
        assert os.environ[ENV_VAR_MODEL] == "all-MiniLM-L6-v2"

    def test_model_info_property(self):
        """model_info should return EmbeddingModelInfo."""
        config = EmbeddingConfig()
        info = config.model_info
        assert isinstance(info, EmbeddingModelInfo)
        assert info.name == config.current_model

    def test_model_info_after_change(self):
        """model_info should reflect current model."""
        config = EmbeddingConfig()
        config.set_model("all-MiniLM-L6-v2")
        info = config.model_info
        assert info.name == "all-MiniLM-L6-v2"
        assert info.size_mb == 22

    def test_list_models(self):
        """list_models should return model names."""
        models = EmbeddingConfig.list_models()
        assert isinstance(models, list)
        assert DEFAULT_MODEL in models
        assert len(models) == len(AVAILABLE_MODELS)

    def test_get_model_info_valid(self):
        """get_model_info should return info for valid models."""
        info = EmbeddingConfig.get_model_info(DEFAULT_MODEL)
        assert info is not None
        assert info.name == DEFAULT_MODEL

    def test_get_model_info_invalid(self):
        """get_model_info should return None for invalid models."""
        info = EmbeddingConfig.get_model_info("invalid-model")
        assert info is None

    def test_get_all_models_info(self):
        """get_all_models_info should return all models."""
        all_info = EmbeddingConfig.get_all_models_info()
        assert len(all_info) == len(AVAILABLE_MODELS)
        for name, info in all_info.items():
            assert isinstance(info, EmbeddingModelInfo)

    def test_reset_instance(self):
        """reset_instance should clear singleton."""
        config1 = EmbeddingConfig()
        EmbeddingConfig.reset_instance()
        config2 = EmbeddingConfig()
        assert config1 is not config2


class TestModelChangeCallbacks:
    """Tests for model change notification system."""

    def test_callback_registration(self):
        """on_model_change should register callback."""
        config = EmbeddingConfig()
        callback_calls = []

        def callback(old, new):
            callback_calls.append((old, new))

        config.on_model_change(callback)
        config.set_model("all-MiniLM-L6-v2")

        assert len(callback_calls) == 1
        assert callback_calls[0] == (DEFAULT_MODEL, "all-MiniLM-L6-v2")

    def test_callback_not_called_for_same_model(self):
        """Callback should not be called when setting same model."""
        config = EmbeddingConfig()
        callback_calls = []

        def callback(old, new):
            callback_calls.append((old, new))

        config.on_model_change(callback)
        config.set_model(config.current_model)

        assert len(callback_calls) == 0

    def test_multiple_callbacks(self):
        """Multiple callbacks should all be called."""
        config = EmbeddingConfig()
        calls1, calls2 = [], []

        config.on_model_change(lambda o, n: calls1.append((o, n)))
        config.on_model_change(lambda o, n: calls2.append((o, n)))
        config.set_model("all-MiniLM-L6-v2")

        assert len(calls1) == 1
        assert len(calls2) == 1

    def test_callback_error_handling(self):
        """Callback errors should not break model switching."""
        config = EmbeddingConfig()

        def bad_callback(old, new):
            raise ValueError("Callback error")

        config.on_model_change(bad_callback)

        # Should not raise, model should still change
        assert config.set_model("all-MiniLM-L6-v2") is True
        assert config.current_model == "all-MiniLM-L6-v2"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_embedding_config(self):
        """get_embedding_config should return singleton."""
        config1 = get_embedding_config()
        config2 = get_embedding_config()
        assert config1 is config2
        assert isinstance(config1, EmbeddingConfig)

    def test_get_current_embedding_model(self):
        """get_current_embedding_model should return model name."""
        model = get_current_embedding_model()
        assert isinstance(model, str)
        assert model == DEFAULT_MODEL


class TestModelSpecs:
    """Tests for specific model specifications."""

    def test_bge_small_specs(self):
        """BGE small should have correct specs."""
        info = AVAILABLE_MODELS["BAAI/bge-small-en-v1.5"]
        assert info.size_mb == 45
        assert info.dimensions == 384
        assert info.speed == "fast"
        assert info.quality == "better"

    def test_bge_base_specs(self):
        """BGE base should have correct specs."""
        info = AVAILABLE_MODELS["BAAI/bge-base-en-v1.5"]
        assert info.size_mb == 110
        assert info.dimensions == 768
        assert info.speed == "medium"
        assert info.quality == "best"

    def test_minilm_l6_specs(self):
        """MiniLM L6 should have correct specs."""
        info = AVAILABLE_MODELS["all-MiniLM-L6-v2"]
        assert info.size_mb == 22
        assert info.dimensions == 384
        assert info.speed == "fast"
        assert info.quality == "good"

    def test_mpnet_specs(self):
        """MPNet should have correct specs."""
        info = AVAILABLE_MODELS["all-mpnet-base-v2"]
        assert info.size_mb == 420
        assert info.dimensions == 768
        assert info.speed == "slow"
        assert info.quality == "best"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
