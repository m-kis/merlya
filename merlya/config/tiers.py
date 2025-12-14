"""
Merlya Config - Unified Model Tiers.

Centralizes tier configuration for ONNX models used by router and parser.
This avoids code duplication and ensures consistent behavior.

Tiers:
- lightweight: No ONNX models, pattern matching only
- balanced: Smaller, faster ONNX models (distilbert-based)
- performance: Larger, more accurate ONNX models (bert-base)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from loguru import logger


class ModelTier(Enum):
    """Model tier for ONNX-based components."""

    LIGHTWEIGHT = "lightweight"  # No ONNX, pattern matching only
    BALANCED = "balanced"  # Smaller models (distilbert)
    PERFORMANCE = "performance"  # Larger models (bert-base)

    @classmethod
    def from_string(cls, value: str | None) -> ModelTier:
        """
        Convert string to ModelTier, with sensible defaults.

        Args:
            value: Tier string (lightweight/balanced/performance).

        Returns:
            Corresponding ModelTier enum value.
        """
        if not value:
            return cls.BALANCED

        normalized = value.lower().strip()

        try:
            return cls(normalized)
        except ValueError:
            logger.warning(f"Unknown tier '{value}', defaulting to balanced")
            return cls.BALANCED

    @classmethod
    def from_ram_gb(cls, available_gb: float) -> ModelTier:
        """
        Select tier based on available RAM.

        Args:
            available_gb: Available RAM in gigabytes.

        Returns:
            Appropriate ModelTier for the available memory.
        """
        if available_gb >= 4.0:
            return cls.PERFORMANCE
        elif available_gb >= 2.0:
            return cls.BALANCED
        else:
            return cls.LIGHTWEIGHT


@dataclass
class ModelConfig:
    """Configuration for a model at a specific tier."""

    model_id: str
    description: str
    size_mb: float | None = None


# Router embedding models (for intent classification)
ROUTER_MODELS: dict[ModelTier, ModelConfig] = {
    ModelTier.PERFORMANCE: ModelConfig(
        model_id="Xenova/bge-m3",
        description="Large multilingual embedding model",
        size_mb=1200,
    ),
    ModelTier.BALANCED: ModelConfig(
        model_id="Xenova/multilingual-e5-base",
        description="Medium multilingual embedding model",
        size_mb=500,
    ),
    ModelTier.LIGHTWEIGHT: ModelConfig(
        model_id="Xenova/all-MiniLM-L6-v2",
        description="Small fast embedding model (fallback)",
        size_mb=90,
    ),
}

# Parser NER models (for entity extraction)
PARSER_MODELS: dict[ModelTier, ModelConfig] = {
    ModelTier.PERFORMANCE: ModelConfig(
        model_id="Xenova/bert-base-NER",
        description="BERT-base NER model (more accurate)",
        size_mb=440,
    ),
    ModelTier.BALANCED: ModelConfig(
        model_id="Xenova/distilbert-NER",
        description="DistilBERT NER model (faster)",
        size_mb=260,
    ),
    ModelTier.LIGHTWEIGHT: ModelConfig(
        model_id="",  # No model, uses heuristic parsing
        description="Heuristic parsing only",
        size_mb=0,
    ),
}


def _normalize_tier(tier: ModelTier | str | None) -> ModelTier:
    """Normalize tier input to ModelTier enum."""
    if isinstance(tier, ModelTier):
        return tier
    if isinstance(tier, str):
        return ModelTier.from_string(tier)
    return ModelTier.BALANCED


def _get_model_id(tier: ModelTier | str | None, models: dict[ModelTier, ModelConfig]) -> str:
    """Get model ID from a models dict for the given tier."""
    normalized = _normalize_tier(tier)
    return models[normalized].model_id


def get_router_model_id(tier: ModelTier | str | None) -> str:
    """
    Get router model ID for the given tier.

    Args:
        tier: ModelTier enum or string.

    Returns:
        Model ID string.
    """
    return _get_model_id(tier, ROUTER_MODELS)


def get_parser_model_id(tier: ModelTier | str | None) -> str:
    """
    Get parser model ID for the given tier.

    Args:
        tier: ModelTier enum or string.

    Returns:
        Model ID string, or empty string for lightweight.
    """
    return _get_model_id(tier, PARSER_MODELS)


def resolve_model_path(model_id: str, subdir: str = "onnx") -> Path:
    """
    Resolve local path for a HuggingFace model.

    Args:
        model_id: Model ID in format "org/model".
        subdir: Subdirectory under ~/.merlya/models/ (default: "onnx").

    Returns:
        Path to the model.onnx file.

    Raises:
        ValueError: If model_id is empty.
    """
    if not model_id:
        raise ValueError("model_id cannot be empty")

    # Normalize model ID for filesystem
    safe_name = model_id.replace("/", "__").replace(":", "__")

    # Use ~/.merlya/models/{subdir}/ directory
    models_dir = Path.home() / ".merlya" / "models" / subdir
    model_path = models_dir / safe_name / "model.onnx"

    return model_path


def resolve_router_model_path(model_id: str) -> Path:
    """Resolve path for router embedding model."""
    return resolve_model_path(model_id, subdir="onnx")


def resolve_parser_model_path(model_id: str) -> Path:
    """Resolve path for parser NER model."""
    return resolve_model_path(model_id, subdir="parser")


def is_model_available(model_id: str, subdir: str = "onnx") -> bool:
    """
    Check if a model is available locally.

    Args:
        model_id: Model ID to check.
        subdir: Subdirectory under ~/.merlya/models/.

    Returns:
        True if model exists locally.
    """
    if not model_id:
        return True  # No model needed for lightweight

    model_path = resolve_model_path(model_id, subdir=subdir)
    tokenizer_path = model_path.parent / "tokenizer.json"

    return model_path.exists() and tokenizer_path.exists()


def get_available_tier() -> ModelTier:
    """
    Get the best available tier based on downloaded models.

    Returns:
        Highest tier with available models.
    """
    for tier in [ModelTier.PERFORMANCE, ModelTier.BALANCED]:
        router_model = get_router_model_id(tier)
        if router_model and is_model_available(router_model):
            return tier

    return ModelTier.LIGHTWEIGHT
