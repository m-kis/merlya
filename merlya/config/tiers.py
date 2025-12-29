"""
Merlya Config - Model Tiers (Deprecated).

ONNX model tiers have been removed in v0.8.0.
This module is kept for backward compatibility only.

Previous tiers:
- lightweight: No ONNX models, pattern matching only
- balanced: Smaller, faster ONNX models (distilbert-based)
- performance: Larger, more accurate ONNX models (bert-base)

Now: All routing uses pattern matching + LLM fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from loguru import logger


class ModelTier(Enum):
    """Model tier for components (deprecated - ONNX removed)."""

    LIGHTWEIGHT = "lightweight"  # Pattern matching only
    BALANCED = "balanced"  # Kept for compatibility
    PERFORMANCE = "performance"  # Kept for compatibility

    @classmethod
    def from_string(cls, value: str | None) -> ModelTier:
        """Convert string to ModelTier, with sensible defaults."""
        if not value:
            return cls.LIGHTWEIGHT

        normalized = value.lower().strip()

        try:
            return cls(normalized)
        except ValueError:
            logger.warning(f"Unknown tier '{value}', defaulting to lightweight")
            return cls.LIGHTWEIGHT

    @classmethod
    def from_ram_gb(cls, available_gb: float) -> ModelTier:
        """Select tier based on available RAM (deprecated - always lightweight)."""
        _ = available_gb
        return cls.LIGHTWEIGHT


@dataclass
class ModelConfig:
    """Configuration for a model at a specific tier (deprecated)."""

    model_id: str
    description: str
    size_mb: float | None = None


# Router embedding models - deprecated, kept for compatibility
ROUTER_MODELS: dict[ModelTier, ModelConfig] = {
    ModelTier.PERFORMANCE: ModelConfig(
        model_id="",
        description="ONNX removed in v0.8.0",
        size_mb=0,
    ),
    ModelTier.BALANCED: ModelConfig(
        model_id="",
        description="ONNX removed in v0.8.0",
        size_mb=0,
    ),
    ModelTier.LIGHTWEIGHT: ModelConfig(
        model_id="",
        description="Pattern matching only",
        size_mb=0,
    ),
}

# Parser NER models - deprecated, kept for compatibility
PARSER_MODELS: dict[ModelTier, ModelConfig] = {
    ModelTier.PERFORMANCE: ModelConfig(
        model_id="",
        description="ONNX removed in v0.8.0",
        size_mb=0,
    ),
    ModelTier.BALANCED: ModelConfig(
        model_id="",
        description="ONNX removed in v0.8.0",
        size_mb=0,
    ),
    ModelTier.LIGHTWEIGHT: ModelConfig(
        model_id="",
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
    return ModelTier.LIGHTWEIGHT


def _get_model_id(tier: ModelTier | str | None, models: dict[ModelTier, ModelConfig]) -> str:
    """Get model ID from a models dict for the given tier."""
    normalized = _normalize_tier(tier)
    return models[normalized].model_id


def get_router_model_id(_tier: ModelTier | str | None) -> str:
    """Get router model ID for the given tier (deprecated - returns empty)."""
    return ""


def get_parser_model_id(_tier: ModelTier | str | None) -> str:
    """Get parser model ID for the given tier (deprecated - returns empty)."""
    return ""


def resolve_model_path(model_id: str, subdir: str = "onnx") -> Path:
    """Resolve local path for a model (deprecated - no models used)."""
    if not model_id:
        raise ValueError("model_id cannot be empty")

    safe_name = model_id.replace("/", "__").replace(":", "__")
    models_dir = Path.home() / ".merlya" / "models" / subdir
    return models_dir / safe_name / "model.onnx"


def resolve_router_model_path(model_id: str) -> Path:
    """Resolve path for router embedding model (deprecated)."""
    return resolve_model_path(model_id, subdir="onnx")


def resolve_parser_model_path(model_id: str) -> Path:
    """Resolve path for parser NER model (deprecated)."""
    return resolve_model_path(model_id, subdir="parser")


def is_model_available(_model_id: str, _subdir: str = "onnx") -> bool:
    """Check if a model is available locally (deprecated - always False)."""
    return False


def get_available_tier() -> ModelTier:
    """Get the best available tier (deprecated - always lightweight)."""
    return ModelTier.LIGHTWEIGHT
