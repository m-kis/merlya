"""
Merlya Router - Intent Classifier Implementation.

ONNX-based semantic classifier for user intent.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from huggingface_hub import hf_hub_download
from loguru import logger

if TYPE_CHECKING:
    from numpy.typing import NDArray


class AgentMode(str, Enum):
    """Agent operating mode."""

    DIAGNOSTIC = "diagnostic"
    REMEDIATION = "remediation"
    QUERY = "query"
    CHAT = "chat"


# Pre-computed embeddings for intent classification
INTENT_EMBEDDINGS: dict[AgentMode, list[str]] = {
    AgentMode.DIAGNOSTIC: [
        "check the status of the server",
        "show me the current CPU usage",
        "what is the disk space on this host",
        "scan the system for issues",
        "list all running processes",
        "verify the service is running",
        "analyze the logs for errors",
        "inspect the configuration",
    ],
    AgentMode.REMEDIATION: [
        "restart the nginx service",
        "fix the permission issue",
        "deploy the new version",
        "update the configuration file",
        "clean up old log files",
        "remove the temporary files",
        "install the package",
        "rollback to previous version",
    ],
    AgentMode.QUERY: [
        "explain how to configure SSH",
        "what is the difference between TCP and UDP",
        "how do I set up a firewall",
        "why is the server slow",
        "describe the architecture",
        "help me understand this error",
    ],
    AgentMode.CHAT: [
        "hello",
        "thank you for your help",
        "goodbye",
        "who are you",
        "what can you do",
    ],
}

# Intent patterns for pattern-based classification (fallback)
INTENT_PATTERNS: dict[AgentMode, list[str]] = {
    AgentMode.DIAGNOSTIC: [
        "check",
        "status",
        "monitor",
        "analyze",
        "debug",
        "diagnose",
        "health",
        "inspect",
        "verify",
        "scan",
        "look at",
        "what is",
        "show me",
        "list",
        "find",
        "search",
        "view",
        "display",
    ],
    AgentMode.REMEDIATION: [
        "fix",
        "repair",
        "restart",
        "stop",
        "start",
        "deploy",
        "install",
        "configure",
        "update",
        "upgrade",
        "rollback",
        "clean",
        "remove",
        "delete",
        "create",
        "change",
        "modify",
        "set",
        "enable",
        "disable",
    ],
    AgentMode.QUERY: [
        "how",
        "why",
        "when",
        "where",
        "explain",
        "describe",
        "tell me",
        "what does",
        "difference between",
        "compare",
        "help me understand",
        "what is the best",
        "should i",
    ],
    AgentMode.CHAT: [
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank you",
        "bye",
        "goodbye",
        "who are you",
        "what can you do",
        "help",
    ],
}

# Tool activation keywords
TOOL_KEYWORDS: dict[str, list[str]] = {
    "system": [
        "cpu",
        "memory",
        "ram",
        "disk",
        "process",
        "pid",
        "service",
        "uptime",
        "load",
        "system",
        "os",
        "kernel",
        "performance",
    ],
    "files": [
        "file",
        "directory",
        "folder",
        "config",
        "log",
        "read",
        "write",
        "copy",
        "move",
        "permission",
        "path",
        "content",
    ],
    "security": [
        "security",
        "port",
        "firewall",
        "ssh",
        "key",
        "certificate",
        "ssl",
        "tls",
        "audit",
        "permission",
        "vulnerability",
        "password",
    ],
    "docker": [
        "docker",
        "container",
        "image",
        "dockerfile",
        "compose",
        "registry",
    ],
    "kubernetes": [
        "kubernetes",
        "k8s",
        "pod",
        "deployment",
        "service",
        "kubectl",
        "helm",
        "namespace",
        "ingress",
    ],
    "web_search": [
        "search",
        "google",
        "duckduckgo",
        "internet",
        "web",
        "docs",
        "documentation",
        "article",
    ],
}


class IntentClassifier:
    """
    Intent classifier for user input.

    Uses ONNX embedding model for semantic classification,
    with pattern matching as fallback.
    """

    # Confidence threshold for LLM fallback
    CONFIDENCE_THRESHOLD = 0.6

    # Class-level flag to prevent duplicate warnings
    _onnx_warning_shown: bool = False

    # Embedding cache settings
    EMBEDDING_CACHE_MAX_SIZE = 1000

    def __init__(
        self,
        use_embeddings: bool = True,
        model_id: str | None = None,
        tier: str | None = None,
    ) -> None:
        """
        Initialize classifier.

        Args:
            use_embeddings: Whether to use ONNX embedding model.
        """
        self.use_embeddings = use_embeddings
        self._model_id = model_id
        self._tier = tier
        self._session: object | None = None  # onnxruntime.InferenceSession
        self._tokenizer: object | None = None  # transformers.AutoTokenizer
        self._model_loaded = False
        self._intent_vectors: dict[AgentMode, NDArray[np.float32]] = {}
        self._embedding_dim: int | None = None
        # LRU cache using OrderedDict for O(1) operations
        self._embedding_cache: OrderedDict[str, NDArray[np.float32]] = OrderedDict()

    async def load_model(self, model_path: Path | None = None, *, allow_download: bool = True) -> bool:
        """Load ONNX embedding model.

        Args:
            model_path: Optional explicit model path override.
            allow_download: If True, missing assets are downloaded automatically.
                Health checks should set this to False to avoid unexpected network downloads.
        """
        if not self.use_embeddings:
            return True

        try:
            import onnxruntime as ort  # noqa: F401 - check availability
            from tokenizers import Tokenizer  # noqa: F401 - check availability

            selected_model = self._select_model_id(self._model_id, self._tier)
            selected_path = model_path or self._resolve_model_path(selected_model)
            tokenizer_path = selected_path.parent / "tokenizer.json"
            data_path = selected_path.with_name(f"{selected_path.name}_data")

            if (not selected_path.exists() or not tokenizer_path.exists()) and not allow_download:
                return self._disable_embeddings(selected_path, tokenizer_path)

            if not selected_path.exists() or not tokenizer_path.exists():
                downloaded = await self._download_model(selected_model, selected_path, tokenizer_path)
                if not downloaded:
                    from merlya.config.tiers import get_router_model_id

                    fallback_model = get_router_model_id(self._tier)
                    if fallback_model and fallback_model != selected_model:
                        logger.warning(
                            f"⚠️ Falling back to default router model for tier '{self._tier}': {fallback_model}"
                        )
                        selected_model = fallback_model
                        selected_path = self._resolve_model_path(selected_model)
                        tokenizer_path = selected_path.parent / "tokenizer.json"
                        data_path = selected_path.with_name(f"{selected_path.name}_data")

                        if not allow_download:
                            return self._disable_embeddings(selected_path, tokenizer_path)

                        await self._download_model(selected_model, selected_path, tokenizer_path)
            elif not data_path.exists():
                if allow_download:
                    await self._download_external_data(selected_model, selected_path)

            if not selected_path.exists() or not tokenizer_path.exists():
                return self._disable_embeddings(selected_path, tokenizer_path)

            # Load in thread to avoid blocking
            self._session, self._tokenizer = await asyncio.to_thread(
                self._load_onnx_and_tokenizer, selected_path, tokenizer_path
            )

            # Pre-compute intent embeddings
            await self._precompute_intent_vectors()

            self._model_loaded = True
            self._model_id = selected_model
            logger.info(f"✅ ONNX embedding model loaded: {selected_model}")
            return True

        except ImportError as e:
            logger.warning(f"⚠️ onnxruntime not installed: {e}")
            self.use_embeddings = False
            return False
        except Exception as e:
            logger.error(f"❌ Failed to load embedding model: {e}")
            self.use_embeddings = False
            return False

    def _load_onnx_and_tokenizer(self, model_path: Path, tokenizer_path: Path) -> tuple[Any, Any]:
        """Load ONNX session and tokenizer (runs in thread)."""
        import onnxruntime as ort
        from tokenizers import Tokenizer

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(str(model_path), sess_options)
        tok = Tokenizer.from_file(str(tokenizer_path))
        return sess, tok

    def _disable_embeddings(self, model_path: Path, tokenizer_path: Path) -> bool:
        """Disable embeddings and log warning."""
        if not IntentClassifier._onnx_warning_shown:
            if not model_path.exists():
                logger.warning(f"⚠️ ONNX model not found: {model_path}")
            elif not tokenizer_path.exists():
                logger.warning(f"⚠️ Tokenizer not found: {tokenizer_path}")
            logger.info("ℹ️ Using pattern matching for intent classification")
            IntentClassifier._onnx_warning_shown = True
        self.use_embeddings = False
        return False

    async def _download_model(
        self,
        model_id: str,
        model_path: Path,
        tokenizer_path: Path,
    ) -> bool:
        """Download ONNX embedding model and tokenizer (plus external data if present)."""
        try:
            target_dir = model_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"🔽 Downloading router model: {model_id}...")
            onnx_src = hf_hub_download(repo_id=model_id, filename="onnx/model.onnx")
            tokenizer_src = hf_hub_download(repo_id=model_id, filename="tokenizer.json")

            # Copy to Merlya model directory
            model_path.write_bytes(Path(onnx_src).read_bytes())
            tokenizer_path.write_bytes(Path(tokenizer_src).read_bytes())

            await self._download_external_data(model_id, model_path)

            logger.info(f"✅ Downloaded ONNX model to {model_path}")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Could not download ONNX model: {e}")
            return False

    async def _download_external_data(self, model_id: str, model_path: Path) -> None:
        """Download external data sidecar if the model uses one."""
        data_candidates = ["onnx/model.onnx_data", "onnx/model.onnx.data"]
        for candidate in data_candidates:
            try:
                data_src = hf_hub_download(repo_id=model_id, filename=candidate)
                data_dest = model_path.with_name(f"{model_path.name}_data")
                Path(data_dest).write_bytes(Path(data_src).read_bytes())
                logger.info(f"✅ Downloaded ONNX external data to {data_dest}")
                return
            except Exception:
                continue
        logger.debug("No external ONNX data sidecar found for {}", model_id)

    def _select_model_id(self, model_id: str | None, tier: str | None) -> str:
        """Select embedding model based on tier using centralized config."""
        from merlya.config.tiers import get_router_model_id

        if model_id:
            return model_id

        return get_router_model_id(tier)

    def _resolve_model_path(self, model_id: str) -> Path:
        """Resolve model path based on model id using centralized config."""
        from merlya.config.tiers import resolve_model_path

        return resolve_model_path(model_id)

    @property
    def model_id(self) -> str | None:
        """Return the current model id."""
        return self._model_id

    async def _precompute_intent_vectors(self) -> None:
        """Pre-compute average embeddings for each intent category."""
        for mode, examples in INTENT_EMBEDDINGS.items():
            embeddings = []
            for text in examples:
                emb = await self._get_embedding(text)
                if emb is not None:
                    embeddings.append(emb)

            if embeddings:
                vector = np.mean(embeddings, axis=0)
                self._intent_vectors[mode] = vector
                if self._embedding_dim is None:
                    self._embedding_dim = int(vector.shape[-1])

        logger.debug(f"🧠 Pre-computed {len(self._intent_vectors)} intent vectors")

    async def _get_embedding(self, text: str) -> NDArray[np.float32] | None:
        """Get embedding vector for text using ONNX model with LRU caching."""
        if not self._session or not self._tokenizer:
            return None

        # Check cache first (O(1) with OrderedDict)
        if text in self._embedding_cache:
            self._embedding_cache.move_to_end(text)  # O(1) LRU update
            return self._embedding_cache[text]

        try:
            encoding = self._tokenizer.encode(text)  # type: ignore[attr-defined]
            input_ids = np.array([encoding.ids], dtype=np.int64)
            attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

            # Build inputs dynamically based on model signature
            model_inputs = {i.name for i in self._session.get_inputs()}  # type: ignore[attr-defined]
            run_inputs: dict[str, NDArray[np.int64]] = {"input_ids": input_ids}
            if "attention_mask" in model_inputs:
                run_inputs["attention_mask"] = attention_mask
            if "token_type_ids" in model_inputs:
                run_inputs["token_type_ids"] = token_type_ids

            def _infer() -> NDArray[np.float32]:
                outputs = self._session.run(  # type: ignore[union-attr]
                    None,
                    run_inputs,
                )
                # Mean pooling over sequence
                embeddings = outputs[0]
                mask = run_inputs.get("attention_mask", attention_mask)
                mask_expanded = mask[:, :, np.newaxis].astype(np.float32)
                sum_embeddings = np.sum(embeddings * mask_expanded, axis=1)
                sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
                return (sum_embeddings / sum_mask)[0]  # type: ignore[no-any-return]

            result = await asyncio.to_thread(_infer)

            # Store in cache with LRU eviction (O(1) with OrderedDict)
            if len(self._embedding_cache) >= self.EMBEDDING_CACHE_MAX_SIZE:
                self._embedding_cache.popitem(last=False)  # Remove oldest

            self._embedding_cache[text] = result
            return result

        except Exception as e:
            logger.debug(f"Embedding error: {e}")
            return None

    async def classify_embeddings(self, text: str) -> tuple[AgentMode, float]:
        """Classify using embedding similarity."""
        text_embedding = await self._get_embedding(text)
        if text_embedding is None:
            return self.classify_patterns(text.lower())

        # Compute similarity with each intent
        similarities: dict[AgentMode, float] = {}
        for mode, intent_vector in self._intent_vectors.items():
            sim = self._cosine_similarity(text_embedding, intent_vector)
            similarities[mode] = sim

        # Get best match
        best_mode = max(similarities, key=lambda m: similarities[m])
        confidence = similarities[best_mode]

        # Normalize to 0-1 range (cosine sim is -1 to 1)
        confidence = (confidence + 1) / 2

        logger.debug(f"🧠 Embedding classification: {best_mode.value} ({confidence:.2f})")

        return best_mode, confidence

    def classify_patterns(self, text: str) -> tuple[AgentMode, float]:
        """Classify using keyword pattern matching (fallback)."""
        scores: dict[AgentMode, float] = dict.fromkeys(AgentMode, 0.0)

        for mode, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    scores[mode] += 1.0

        # Normalize scores
        total = sum(scores.values())
        if total > 0:
            for mode in scores:
                scores[mode] /= total

        # Get best mode
        best_mode = max(scores, key=lambda m: scores[m])
        confidence = scores[best_mode]

        # Default to chat if no clear intent
        if confidence < 0.2:
            return AgentMode.CHAT, 0.5

        return best_mode, confidence

    def determine_tools(self, text: str, entities: dict[str, list[str]]) -> list[str]:
        """Determine which tools to activate."""
        tools = ["core"]  # Core tools always active

        for tool_category, keywords in TOOL_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                tools.append(tool_category)

        # If hosts mentioned, add system tools
        if entities.get("hosts") and "system" not in tools:
            tools.append("system")

        return tools

    def extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract entities from text."""
        import re

        entities: dict[str, list[str]] = {
            "hosts": [],
            "variables": [],
            "files": [],
        }

        # Extract @mentions (hosts or variables)
        mentions = re.findall(r"@(\w[\w.-]*)", text)
        for mention in mentions:
            # Heuristic:
            # - Variables/secrets often have underscores OR any uppercase (MY_VAR, apiKey, MotDePasse)
            # - Hosts are typically lowercase with dashes/digits/domains
            if "_" in mention or any(c.isupper() for c in mention):
                entities["variables"].append(mention)
            else:
                entities["hosts"].append(mention)

        # Extract file paths
        paths = re.findall(r"(/[\w/.-]+|\./[\w/.-]+|~/[\w/.-]+)", text)
        entities["files"] = paths

        return entities

    def check_delegation(self, text: str) -> str | None:
        """Check if should delegate to specialized agent."""
        for agent, keywords in TOOL_KEYWORDS.items():
            if agent in ["docker", "kubernetes"] and any(kw in text for kw in keywords):
                return agent
        return None

    def _cosine_similarity(self, a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    @property
    def model_loaded(self) -> bool:
        """Return True if the ONNX model is loaded."""
        return self._model_loaded

    @property
    def embedding_dim(self) -> int | None:
        """Return embedding dimension if available."""
        return self._embedding_dim
