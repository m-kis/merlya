"""
Tests for unified tier configuration.
"""

from pathlib import Path

import pytest

from merlya.config.tiers import (
    PARSER_MODELS,
    ROUTER_MODELS,
    ModelTier,
    get_parser_model_id,
    get_router_model_id,
    is_model_available,
    resolve_model_path,
    resolve_parser_model_path,
    resolve_router_model_path,
)


class TestModelTier:
    """Tests for ModelTier enum."""

    def test_tier_values(self):
        """Test tier enum has expected values."""
        assert ModelTier.LIGHTWEIGHT.value == "lightweight"
        assert ModelTier.BALANCED.value == "balanced"
        assert ModelTier.PERFORMANCE.value == "performance"

    def test_from_string_valid(self):
        """Test from_string with valid values."""
        assert ModelTier.from_string("lightweight") == ModelTier.LIGHTWEIGHT
        assert ModelTier.from_string("balanced") == ModelTier.BALANCED
        assert ModelTier.from_string("performance") == ModelTier.PERFORMANCE

    def test_from_string_case_insensitive(self):
        """Test from_string is case insensitive."""
        assert ModelTier.from_string("BALANCED") == ModelTier.BALANCED
        assert ModelTier.from_string("Performance") == ModelTier.PERFORMANCE

    def test_from_string_invalid(self):
        """Test from_string with invalid value defaults to balanced."""
        assert ModelTier.from_string("invalid") == ModelTier.BALANCED
        assert ModelTier.from_string("") == ModelTier.BALANCED
        assert ModelTier.from_string(None) == ModelTier.BALANCED

    def test_from_ram_gb(self):
        """Test from_ram_gb tier selection."""
        assert ModelTier.from_ram_gb(8.0) == ModelTier.PERFORMANCE
        assert ModelTier.from_ram_gb(4.0) == ModelTier.PERFORMANCE
        assert ModelTier.from_ram_gb(3.0) == ModelTier.BALANCED
        assert ModelTier.from_ram_gb(2.0) == ModelTier.BALANCED
        assert ModelTier.from_ram_gb(1.0) == ModelTier.LIGHTWEIGHT
        assert ModelTier.from_ram_gb(0.5) == ModelTier.LIGHTWEIGHT


class TestRouterModels:
    """Tests for router model configuration."""

    def test_all_tiers_have_config(self):
        """Test all tiers have router model config."""
        assert ModelTier.LIGHTWEIGHT in ROUTER_MODELS
        assert ModelTier.BALANCED in ROUTER_MODELS
        assert ModelTier.PERFORMANCE in ROUTER_MODELS

    def test_model_ids_valid(self):
        """Test router model IDs are valid HuggingFace format."""
        for tier, config in ROUTER_MODELS.items():
            if tier != ModelTier.LIGHTWEIGHT:  # Lightweight may have empty model_id
                assert "/" in config.model_id or config.model_id == ""
            assert config.description

    def test_get_router_model_id_with_enum(self):
        """Test get_router_model_id with enum."""
        assert get_router_model_id(ModelTier.PERFORMANCE) == "Xenova/bge-m3"
        assert get_router_model_id(ModelTier.BALANCED) == "Xenova/multilingual-e5-base"

    def test_get_router_model_id_with_string(self):
        """Test get_router_model_id with string."""
        assert get_router_model_id("performance") == "Xenova/bge-m3"
        assert get_router_model_id("balanced") == "Xenova/multilingual-e5-base"

    def test_get_router_model_id_default(self):
        """Test get_router_model_id defaults to balanced."""
        assert get_router_model_id(None) == ROUTER_MODELS[ModelTier.BALANCED].model_id


class TestParserModels:
    """Tests for parser model configuration."""

    def test_all_tiers_have_config(self):
        """Test all tiers have parser model config."""
        assert ModelTier.LIGHTWEIGHT in PARSER_MODELS
        assert ModelTier.BALANCED in PARSER_MODELS
        assert ModelTier.PERFORMANCE in PARSER_MODELS

    def test_model_ids_valid(self):
        """Test parser model IDs are valid HuggingFace format."""
        for tier, config in PARSER_MODELS.items():
            if tier != ModelTier.LIGHTWEIGHT:
                assert "/" in config.model_id
            assert config.description

    def test_get_parser_model_id_with_enum(self):
        """Test get_parser_model_id with enum."""
        assert get_parser_model_id(ModelTier.PERFORMANCE) == "Xenova/bert-base-NER"
        assert get_parser_model_id(ModelTier.BALANCED) == "Xenova/distilbert-NER"

    def test_get_parser_model_id_with_string(self):
        """Test get_parser_model_id with string."""
        assert get_parser_model_id("performance") == "Xenova/bert-base-NER"
        assert get_parser_model_id("balanced") == "Xenova/distilbert-NER"


class TestModelPaths:
    """Tests for model path resolution."""

    def test_resolve_model_path_format(self):
        """Test resolve_model_path returns correct format."""
        path = resolve_model_path("Xenova/bge-m3")
        assert isinstance(path, Path)
        assert path.name == "model.onnx"
        assert "Xenova__bge-m3" in str(path)
        assert "onnx" in str(path)  # default subdir

    def test_resolve_model_path_with_subdir(self):
        """Test resolve_model_path with custom subdir."""
        path = resolve_model_path("Xenova/model", subdir="parser")
        assert "parser" in str(path)
        assert "Xenova__model" in str(path)

    def test_resolve_model_path_special_chars(self):
        """Test resolve_model_path handles special characters."""
        path = resolve_model_path("org/model:version")
        assert "org__model__version" in str(path)

    def test_resolve_model_path_empty_raises(self):
        """Test resolve_model_path raises ValueError for empty model_id."""
        with pytest.raises(ValueError, match="cannot be empty"):
            resolve_model_path("")

    def test_resolve_router_model_path(self):
        """Test resolve_router_model_path uses onnx subdir."""
        path = resolve_router_model_path("Xenova/bge-m3")
        assert "onnx" in str(path)
        assert "Xenova__bge-m3" in str(path)

    def test_resolve_parser_model_path(self):
        """Test resolve_parser_model_path uses parser subdir."""
        path = resolve_parser_model_path("Xenova/bert-base-NER")
        assert "parser" in str(path)
        assert "Xenova__bert-base-NER" in str(path)

    def test_is_model_available_empty_id(self):
        """Test is_model_available with empty model_id returns True."""
        assert is_model_available("") is True

    def test_is_model_available_nonexistent(self):
        """Test is_model_available with nonexistent model returns False."""
        assert is_model_available("nonexistent/model") is False

    def test_is_model_available_with_subdir(self):
        """Test is_model_available respects subdir parameter."""
        # Both should return False for nonexistent models
        assert is_model_available("nonexistent/model", subdir="onnx") is False
        assert is_model_available("nonexistent/model", subdir="parser") is False
