"""
Merlya Router - Intent Classifier Implementation.

ONNX-based semantic classifier for user intent.
"""

from __future__ import annotations

import asyncio
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

    def __init__(self, use_embeddings: bool = True) -> None:
        """
        Initialize classifier.

        Args:
            use_embeddings: Whether to use ONNX embedding model.
        """
        self.use_embeddings = use_embeddings
        self._session: object | None = None  # onnxruntime.InferenceSession
        self._tokenizer: object | None = None  # transformers.AutoTokenizer
        self._model_loaded = False
        self._intent_vectors: dict[AgentMode, NDArray[np.float32]] = {}
        self._embedding_dim: int | None = None

    async def load_model(self, model_path: Path | None = None) -> bool:
        """Load ONNX embedding model."""
        if not self.use_embeddings:
            return True

        try:
            import onnxruntime as ort  # noqa: F401 - check availability
            from tokenizers import Tokenizer  # noqa: F401 - check availability

            model_path = model_path or Path.home() / ".merlya" / "models" / "router.onnx"
            tokenizer_path = model_path.parent / "tokenizer.json"

            if not model_path.exists():
                await self._download_model(model_path, tokenizer_path)

            if not model_path.exists() or not tokenizer_path.exists():
                return self._disable_embeddings(model_path, tokenizer_path)

            # Load in thread to avoid blocking
            self._session, self._tokenizer = await asyncio.to_thread(
                self._load_onnx_and_tokenizer, model_path, tokenizer_path
            )

            # Pre-compute intent embeddings
            await self._precompute_intent_vectors()

            self._model_loaded = True
            logger.info(f"✅ ONNX embedding model loaded: {model_path.name}")
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
            logger.info("ℹ️ Using pattern matching for intent classification")  # noqa: RUF001
            IntentClassifier._onnx_warning_shown = True
        self.use_embeddings = False
        return False

    async def _download_model(self, model_path: Path, tokenizer_path: Path) -> None:
        """Download default ONNX embedding model."""
        try:
            target_dir = model_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)

            logger.info("🔽 Downloading default ONNX router model (MiniLM)...")
            onnx_src = hf_hub_download(
                repo_id="Xenova/all-MiniLM-L6-v2",
                filename="onnx/model.onnx",
            )
            tokenizer_src = hf_hub_download(
                repo_id="Xenova/all-MiniLM-L6-v2",
                filename="tokenizer.json",
            )

            # Copy to Merlya model directory
            model_path.write_bytes(Path(onnx_src).read_bytes())
            tokenizer_path.write_bytes(Path(tokenizer_src).read_bytes())
            logger.info(f"✅ Downloaded ONNX model to {model_path}")
        except Exception as e:
            logger.warning(f"⚠️ Could not download ONNX model: {e}")

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
        """Get embedding vector for text using ONNX model."""
        if not self._session or not self._tokenizer:
            return None

        try:
            encoding = self._tokenizer.encode(text)  # type: ignore[attr-defined]
            input_ids = np.array([encoding.ids], dtype=np.int64)
            attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

            def _infer() -> NDArray[np.float32]:
                outputs = self._session.run(  # type: ignore[union-attr]
                    None,
                    {
                        "input_ids": input_ids,
                        "attention_mask": attention_mask,
                        "token_type_ids": token_type_ids,
                    },
                )
                # Mean pooling over sequence
                embeddings = outputs[0]
                mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
                sum_embeddings = np.sum(embeddings * mask_expanded, axis=1)
                sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
                return (sum_embeddings / sum_mask)[0]  # type: ignore[no-any-return]

            return await asyncio.to_thread(_infer)

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
            # Variables usually have underscores, hosts have dashes
            if "_" in mention or mention.isupper():
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
