"""
Embedding Cache for Smart Triage Classifier.
"""

import hashlib
import os
from typing import Dict, List, Optional

from merlya.utils.logger import logger

from ..embedding_config import get_embedding_config

# Disable tokenizers parallelism to avoid fork warnings
# This must be set before loading sentence-transformers
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Optional imports for embeddings
try:
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    np = None  # type: ignore
    torch = None  # type: ignore
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
            self._model = self._load_model(self._model_name)
        return self._model

    def _load_model(self, model_name: str) -> "SentenceTransformer":
        """
        Load a SentenceTransformer model with proper device handling.

        This handles the 'meta tensor' error that occurs when switching models,
        by ensuring proper device placement during model loading.

        Args:
            model_name: Name or path of the model to load

        Returns:
            Loaded SentenceTransformer model

        Raises:
            RuntimeError: If model loading fails after all attempts
        """
        # Determine the device to use
        device = "cpu"
        if torch is not None:
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"

        try:
            # Clear any cached meta tensors before loading
            if torch is not None:
                torch.cuda.empty_cache() if torch.cuda.is_available() else None

            # Try loading with explicit device to avoid meta tensor issues
            model = SentenceTransformer(
                model_name,
                device=device,
                trust_remote_code=True,  # Some models require this
            )
            return model
        except RuntimeError as e:
            error_msg = str(e).lower()
            # Handle meta tensor error by forcing CPU load first
            if "meta tensor" in error_msg or "cannot copy out of meta" in error_msg:
                logger.warning(
                    f"⚠️ Meta tensor error, attempting alternative loading for: {model_name}"
                )
                try:
                    # Method 1: Try with accelerate's low_cpu_mem_usage disabled
                    try:
                        from transformers import AutoModel
                        # Disable accelerate's lazy loading
                        import os
                        old_val = os.environ.get("TRANSFORMERS_OFFLINE", "")
                        os.environ["TRANSFORMERS_OFFLINE"] = "0"

                        model = SentenceTransformer(
                            model_name,
                            device="cpu",
                            trust_remote_code=True,
                        )
                        os.environ["TRANSFORMERS_OFFLINE"] = old_val
                        logger.info(f"✅ Model loaded successfully on CPU")
                        return model
                    except Exception:
                        pass

                    # Method 2: Try a simpler/smaller fallback model
                    fallback_model = "all-MiniLM-L6-v2"
                    if model_name != fallback_model:
                        logger.warning(
                            f"⚠️ Falling back to simpler model: {fallback_model}"
                        )
                        model = SentenceTransformer(
                            fallback_model,
                            device="cpu",
                            trust_remote_code=True,
                        )
                        self._model_name = fallback_model  # Update stored name
                        return model

                    raise RuntimeError("All loading methods failed")

                except Exception as fallback_error:
                    logger.error(f"❌ All model loading attempts failed: {fallback_error}")
                    raise RuntimeError(
                        f"Failed to load model '{model_name}': {fallback_error}"
                    ) from fallback_error
            else:
                raise

    @property
    def model_name(self) -> str:
        """Get current model name."""
        return self._model_name

    def _get_key(self, text: str) -> str:
        """Generate cache key from text using SHA256."""
        return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:32]

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
