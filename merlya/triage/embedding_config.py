"""
Embedding Model Configuration.

Centralized configuration for sentence-transformers models used in Merlya.
Supports dynamic model switching, file persistence, and environment variable configuration.
"""
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from merlya.utils.logger import logger


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
    # === Multilingual Models (French/English support) ===
    "paraphrase-multilingual-MiniLM-L12-v2": EmbeddingModelInfo(
        name="paraphrase-multilingual-MiniLM-L12-v2",
        size_mb=120,
        dimensions=384,
        speed="medium",
        quality="best",
        description="Multilingual MiniLM - 50+ languages, excellent for FR/EN",
    ),
    "distiluse-base-multilingual-cased-v2": EmbeddingModelInfo(
        name="distiluse-base-multilingual-cased-v2",
        size_mb=270,
        dimensions=512,
        speed="medium",
        quality="best",
        description="DistilUSE multilingual - 50+ languages, semantic search",
    ),
    "intfloat/multilingual-e5-small": EmbeddingModelInfo(
        name="intfloat/multilingual-e5-small",
        size_mb=120,
        dimensions=384,
        speed="fast",
        quality="best",
        description="Multilingual E5 - SOTA for 100+ languages, excellent FR/EN",
    ),
    "intfloat/multilingual-e5-base": EmbeddingModelInfo(
        name="intfloat/multilingual-e5-base",
        size_mb=280,
        dimensions=768,
        speed="medium",
        quality="best",
        description="Multilingual E5 base - Top MTEB multilingual performer",
    ),
}

# Default model - BGE small is the best balance for 2024-2025
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Environment variable for model configuration
ENV_VAR_MODEL = "MERLYA_EMBEDDING_MODEL"


class EmbeddingConfig:
    """
    Centralized embedding model configuration.

    Singleton pattern for consistent configuration across the application.
    Supports:
    - File persistence (~/.merlya/config.json)
    - Environment variable override (MERLYA_EMBEDDING_MODEL)
    - Runtime model switching
    - Model information and listing

    Priority order:
    1. Environment variable (highest priority)
    2. Config file (~/.merlya/config.json)
    3. Default model (lowest priority)
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
        with self._lock:
            if self._initialized:
                return

            # Config file path (shared with llm/model_config.py)
            self._config_dir = Path.home() / ".merlya"
            self._config_file = self._config_dir / "config.json"

            # Priority: env var > config file > default
            self._current_model = self._load_model()

            # Log if using a custom model (not in recommended list)
            if self._current_model not in AVAILABLE_MODELS:
                logger.info(
                    f"ℹ️ Using custom embedding model: {self._current_model} "
                    f"(not in recommended list, will be loaded from HuggingFace)"
                )

            # Callback for model change notifications
            self._on_change_callbacks: List[Callable[[str, str], None]] = []

            self._initialized = True
            logger.debug(f"✅ EmbeddingConfig initialized with model: {self._current_model}")

    def _load_model(self) -> str:
        """
        Load embedding model from config sources.

        Priority: env var > config file > default
        """
        # 1. Environment variable (highest priority)
        env_model = os.getenv(ENV_VAR_MODEL)
        if env_model:
            logger.debug(f"📌 Using embedding model from env var: {env_model}")
            return env_model

        # 2. Config file
        if self._config_file.exists():
            try:
                with open(self._config_file, 'r') as f:
                    config = json.load(f)
                    file_model = config.get("embedding_model")
                    if file_model:
                        logger.debug(f"📌 Using embedding model from config file: {file_model}")
                        return file_model
            except Exception as e:
                logger.warning(f"⚠️ Failed to load embedding model from config: {e}")

        # 3. Default
        logger.debug(f"📌 Using default embedding model: {DEFAULT_MODEL}")
        return DEFAULT_MODEL

    def _save_to_config(self, model_name: str) -> None:
        """
        Save embedding model to config file.

        Merges with existing config to preserve other settings.
        """
        try:
            # Ensure config directory exists
            self._config_dir.mkdir(parents=True, exist_ok=True)

            # Load existing config or create new
            config = {}
            if self._config_file.exists():
                try:
                    with open(self._config_file, 'r') as f:
                        config = json.load(f)
                except Exception:
                    pass

            # Update embedding model
            config["embedding_model"] = model_name

            # Save config
            with open(self._config_file, 'w') as f:
                json.dump(config, f, indent=2)

            logger.debug(f"💾 Saved embedding model to config: {model_name}")

        except Exception as e:
            logger.warning(f"⚠️ Failed to save embedding model to config: {e}")

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

        Accepts any model name that sentence-transformers can load from HuggingFace.
        The AVAILABLE_MODELS list contains recommended models, but you can use any
        compatible model (e.g., "google/gemma-2b", "Alibaba-NLP/gte-large-en-v1.5", etc.)

        Args:
            model_name: Name of the model to use (HuggingFace model ID or local path)

        Returns:
            True if model was changed successfully
        """
        # Warn if using a model not in the recommended list, but allow it
        if model_name not in AVAILABLE_MODELS:
            logger.warning(
                f"⚠️ Using custom embedding model: {model_name}\n"
                f"   This model is not in the recommended list. "
                f"It will be downloaded from HuggingFace on first use.\n"
                f"   Use '/model embedding list' to see recommended models."
            )

        if model_name == self._current_model:
            logger.debug(f"Model already set to {model_name}")
            return True

        old_model = self._current_model
        self._current_model = model_name

        # Persist to config file (survives restarts)
        self._save_to_config(model_name)

        # Also update environment variable for current session
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

    def remove_model_change_callback(self, callback: Callable[[str, str], None]) -> bool:
        """
        Remove a previously registered callback.

        Returns:
            True if callback was found and removed, False otherwise.
        """
        try:
            self._on_change_callbacks.remove(callback)
            return True
        except ValueError:
            return False

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
        with cls._lock:
            cls._instance = None


# Convenience functions
def get_embedding_config() -> EmbeddingConfig:
    """Get the embedding configuration singleton."""
    return EmbeddingConfig()


def get_current_embedding_model() -> str:
    """Get the current embedding model name."""
    return get_embedding_config().current_model
