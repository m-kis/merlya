"""
Embedding Cache for Smart Triage Classifier.
"""

import hashlib
from typing import Dict, List, Optional

from athena_ai.utils.logger import logger

from ..embedding_config import get_embedding_config

# Optional imports for embeddings
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    np = None  # type: ignore
    logger.debug("⚠️ sentence-transformers not installed. Using keyword-only classification.")


class EmbeddingCache:
    """LRU cache for text embeddings to avoid recomputation."""

    def __init__(self, model_name: Optional[str] = None, max_size: int = 1000):
        self._model: Optional["SentenceTransformer"] = None
        # Use centralized config if no model specified
        self._model_name = model_name or get_embedding_config().current_model
        self._cache: Dict[str, "np.ndarray"] = {}
        self._max_size = max_size
        self._access_order: List[str] = []

        # Register for model change notifications (only if using centralized config)
        if model_name is None:
            get_embedding_config().on_model_change(self._on_model_change)

    def _on_model_change(self, old_model: str, new_model: str) -> None:
        """Handle model change - clear cache and reload."""
        logger.info(f"🔄 EmbeddingCache: Model changed {old_model} → {new_model}")
        self._model_name = new_model
        self._model = None  # Force reload on next use
        self._cache.clear()
        self._access_order.clear()

    @property
    def model(self) -> "SentenceTransformer":
        """Lazy load the model."""
        if not HAS_EMBEDDINGS:
            raise RuntimeError(
                "Embedding dependencies are not installed. "
                "Install with: pip install sentence-transformers numpy"
            )
        if self._model is None:
            logger.info(f"🔄 Loading embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def model_name(self) -> str:
        """Get current model name."""
        return self._model_name

    def _get_key(self, text: str) -> str:
        """Generate cache key from text."""
        return hashlib.md5(text.lower().strip().encode()).hexdigest()

    def get_embedding(self, text: str) -> "np.ndarray":
        """Get embedding for text, using cache if available."""
        key = self._get_key(text)

        if key in self._cache:
            # Move to end of access order
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]

        # Compute embedding
        embedding = self.model.encode(text, convert_to_numpy=True)

        # Cache it
        self._cache[key] = embedding
        self._access_order.append(key)

        # Evict if over max size
        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]

        return embedding

    def get_embeddings_batch(self, texts: List[str]) -> List["np.ndarray"]:
        """Get embeddings for multiple texts efficiently."""
        # Split into cached and uncached
        cached = []
        uncached = []
        uncached_indices = []

        for i, text in enumerate(texts):
            key = self._get_key(text)
            if key in self._cache:
                # Update access order for cache hit (LRU behavior)
                if key in self._access_order:
                    self._access_order.remove(key)
                self._access_order.append(key)
                cached.append((i, self._cache[key]))
            else:
                uncached.append(text)
                uncached_indices.append(i)

        # Batch compute uncached
        if uncached:
            new_embeddings = self.model.encode(uncached, convert_to_numpy=True)
            for idx, text, embedding in zip(uncached_indices, uncached, new_embeddings, strict=False):
                key = self._get_key(text)
                self._cache[key] = embedding
                self._access_order.append(key)
                cached.append((idx, embedding))

        # Maintain cache size
        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]

        # Sort by original index and return
        cached.sort(key=lambda x: x[0])
        return [emb for _, emb in cached]
