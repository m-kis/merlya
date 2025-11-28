"""
Embedding Model Configuration.

Centralized configuration for sentence-transformers models used in Athena.
Supports dynamic model switching and environment variable configuration.
"""
import os
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from athena_ai.utils.logger import logger


@dataclass
class EmbeddingModelInfo:
    """Information about an embedding model."""
    name: str
    size_mb: int
    dimensions: int
    speed: str  # "fast", "medium", "slow"
    quality: str  # "good", "better", "best"
    description: str


# Available models with their characteristics (updated 2024-2025)
# Sources: MTEB Leaderboard, HuggingFace, Sentence-Transformers docs
AVAILABLE_MODELS: Dict[str, EmbeddingModelInfo] = {
    # === RECOMMENDED: BGE Models (BAAI - State of the art 2024) ===
    "BAAI/bge-small-en-v1.5": EmbeddingModelInfo(
        name="BAAI/bge-small-en-v1.5",
        size_mb=45,
        dimensions=384,
        speed="fast",
        quality="better",
        description="BGE small - SOTA 2024, excellent for semantic search",
    ),
    "BAAI/bge-base-en-v1.5": EmbeddingModelInfo(
        name="BAAI/bge-base-en-v1.5",
        size_mb=110,
        dimensions=768,
        speed="medium",
        quality="best",
        description="BGE base - Top MTEB performer, best quality/size ratio",
    ),
    # === E5 Models (Microsoft - Strong multilingual) ===
    "intfloat/e5-small-v2": EmbeddingModelInfo(
        name="intfloat/e5-small-v2",
        size_mb=45,
        dimensions=384,
        speed="fast",
        quality="better",
        description="E5 small - Fast multilingual, good for classification",
    ),
    "intfloat/e5-base-v2": EmbeddingModelInfo(
        name="intfloat/e5-base-v2",
        size_mb=110,
        dimensions=768,
        speed="medium",
        quality="best",
        description="E5 base - Strong multilingual support",
    ),
    # === GTE Models (Alibaba - Competitive with BGE) ===
    "thenlper/gte-small": EmbeddingModelInfo(
        name="thenlper/gte-small",
        size_mb=45,
        dimensions=384,
        speed="fast",
        quality="better",
        description="GTE small - Competitive with BGE, fast inference",
    ),
    "thenlper/gte-base": EmbeddingModelInfo(
        name="thenlper/gte-base",
        size_mb=110,
        dimensions=768,
        speed="medium",
        quality="best",
        description="GTE base - Top MTEB performer",
    ),
    # === MiniLM Models (Legacy but proven) ===
    "all-MiniLM-L6-v2": EmbeddingModelInfo(
        name="all-MiniLM-L6-v2",
        size_mb=22,
        dimensions=384,
        speed="fast",
        quality="good",
        description="MiniLM - Proven classic, 5x faster than BERT",
    ),
    "paraphrase-MiniLM-L3-v2": EmbeddingModelInfo(
        name="paraphrase-MiniLM-L3-v2",
        size_mb=17,
        dimensions=384,
        speed="fast",
        quality="good",
        description="Smallest model, ultra-fast, basic quality",
    ),
    # === Multi-QA (Optimized for Q&A) ===
    "multi-qa-MiniLM-L6-cos-v1": EmbeddingModelInfo(
        name="multi-qa-MiniLM-L6-cos-v1",
        size_mb=22,
        dimensions=384,
        speed="fast",
        quality="better",
        description="Optimized for question-answering tasks",
    ),
    # === MPNet (Highest quality legacy) ===
    "all-mpnet-base-v2": EmbeddingModelInfo(
        name="all-mpnet-base-v2",
        size_mb=420,
        dimensions=768,
        speed="slow",
        quality="best",
        description="MPNet - Highest quality legacy model",
    ),
}

# Default model - BGE small is the best balance for 2024-2025
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Environment variable for model configuration
ENV_VAR_MODEL = "ATHENA_EMBEDDING_MODEL"


class EmbeddingConfig:
    """
    Centralized embedding model configuration.

    Singleton pattern for consistent configuration across the application.
    Supports:
    - Environment variable configuration (ATHENA_EMBEDDING_MODEL)
    - Runtime model switching
    - Model information and listing
    """

    _instance: Optional["EmbeddingConfig"] = None
    _lock = threading.Lock()

    def __new__(cls):
        """Thread-safe singleton implementation."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize configuration (once)."""
        if self._initialized:
            return

        # Load from environment or use default
        self._current_model = os.getenv(ENV_VAR_MODEL, DEFAULT_MODEL)

        # Validate model exists
        if self._current_model not in AVAILABLE_MODELS:
            logger.warning(
                f"⚠️ Unknown embedding model '{self._current_model}', "
                f"falling back to '{DEFAULT_MODEL}'"
            )
            self._current_model = DEFAULT_MODEL

        # Callback for model change notifications
        self._on_change_callbacks: List[Callable[[str, str], None]] = []

        self._initialized = True
        logger.debug(f"✅ EmbeddingConfig initialized with model: {self._current_model}")

    @property
    def current_model(self) -> str:
        """Get current embedding model name."""
        return self._current_model

    @property
    def model_info(self) -> EmbeddingModelInfo:
        """Get info about current model."""
        return AVAILABLE_MODELS.get(self._current_model, AVAILABLE_MODELS[DEFAULT_MODEL])

    def set_model(self, model_name: str) -> bool:
        """
        Set the embedding model.

        Args:
            model_name: Name of the model to use

        Returns:
            True if model was changed successfully
        """
        if model_name not in AVAILABLE_MODELS:
            logger.error(f"❌ Unknown embedding model: {model_name}")
            return False

        if model_name == self._current_model:
            logger.debug(f"Model already set to {model_name}")
            return True

        old_model = self._current_model
        self._current_model = model_name

        # Update environment variable for persistence
        os.environ[ENV_VAR_MODEL] = model_name

        logger.info(f"✅ Embedding model changed: {old_model} → {model_name}")

        # Notify callbacks
        for callback in self._on_change_callbacks:
            try:
                callback(old_model, model_name)
            except Exception as e:
                logger.warning(f"⚠️ Model change callback failed: {e}")

        return True

    def on_model_change(self, callback: Callable[[str, str], None]) -> None:
        """
        Register a callback for model changes.

        Callback signature: callback(old_model: str, new_model: str)
        """
        self._on_change_callbacks.append(callback)

    @staticmethod
    def list_models() -> List[str]:
        """List available model names."""
        return list(AVAILABLE_MODELS.keys())

    @staticmethod
    def get_model_info(model_name: str) -> Optional[EmbeddingModelInfo]:
        """Get info about a specific model."""
        return AVAILABLE_MODELS.get(model_name)

    @staticmethod
    def get_all_models_info() -> Dict[str, EmbeddingModelInfo]:
        """Get info about all available models."""
        return AVAILABLE_MODELS.copy()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None


# Convenience functions
def get_embedding_config() -> EmbeddingConfig:
    """Get the embedding configuration singleton."""
    return EmbeddingConfig()


def get_current_embedding_model() -> str:
    """Get the current embedding model name."""
    return get_embedding_config().current_model
