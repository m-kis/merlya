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
    def from_string(cls, value: str | None) -> "ModelTier":
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
    def from_ram_gb(cls, available_gb: float) -> "ModelTier":
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
        model_id="Xenova/gte-multilingual-base",
        description="Medium multilingual embedding model",
        size_mb=400,
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


def get_router_model_id(tier: ModelTier | str | None) -> str:
    """
    Get router model ID for the given tier.

    Args:
        tier: ModelTier enum or string.

    Returns:
        Model ID string, or empty string for lightweight.
    """
    if isinstance(tier, str):
        tier = ModelTier.from_string(tier)
    elif tier is None:
        tier = ModelTier.BALANCED

    return ROUTER_MODELS[tier].model_id


def get_parser_model_id(tier: ModelTier | str | None) -> str:
    """
    Get parser model ID for the given tier.

    Args:
        tier: ModelTier enum or string.

    Returns:
        Model ID string, or empty string for lightweight.
    """
    if isinstance(tier, str):
        tier = ModelTier.from_string(tier)
    elif tier is None:
        tier = ModelTier.BALANCED

    return PARSER_MODELS[tier].model_id


def resolve_model_path(model_id: str) -> Path:
    """
    Resolve local path for a HuggingFace model.

    Args:
        model_id: Model ID in format "org/model".

    Returns:
        Path to the model.onnx file.
    """
    # Normalize model ID for filesystem
    safe_name = model_id.replace("/", "__").replace(":", "__")

    # Use ~/.merlya/models/ directory
    models_dir = Path.home() / ".merlya" / "models" / "onnx"
    model_path = models_dir / safe_name / "model.onnx"

    return model_path


def is_model_available(model_id: str) -> bool:
    """
    Check if a model is available locally.

    Args:
        model_id: Model ID to check.

    Returns:
        True if model exists locally.
    """
    if not model_id:
        return True  # No model needed for lightweight

    model_path = resolve_model_path(model_id)
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
