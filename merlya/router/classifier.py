"""
Merlya Router - Intent Classifier.

Classifies user input to determine agent mode and tools.
Uses local ONNX embedding model or LLM fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from numpy.typing import NDArray


class AgentMode(str, Enum):
    """Agent operating mode."""

    DIAGNOSTIC = "diagnostic"
    REMEDIATION = "remediation"
    QUERY = "query"
    CHAT = "chat"


@dataclass
class RouterResult:
    """Result of intent classification."""

    mode: AgentMode
    tools: list[str]
    entities: dict[str, list[str]] = field(default_factory=dict)
    confidence: float = 0.0
    delegate_to: str | None = None


# Intent patterns for classification
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
    ],
    "docker": [
        "docker",
        "container",
        "image",
        "dockerfile",
        "compose",
    ],
    "kubernetes": [
        "kubernetes",
        "k8s",
        "pod",
        "deployment",
        "service",
        "kubectl",
        "helm",
    ],
}


class IntentClassifier:
    """
    Intent classifier for user input.

    Uses pattern matching for quick classification,
    with optional ONNX embedding for better accuracy.
    """

    def __init__(self, use_embeddings: bool = False) -> None:
        """
        Initialize classifier.

        Args:
            use_embeddings: Whether to use ONNX embedding model.
        """
        self.use_embeddings = use_embeddings
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._embeddings_cache: dict[str, NDArray[np.float32]] = {}

    async def load_model(self, model_path: Path | None = None) -> bool:
        """
        Load ONNX embedding model.

        Args:
            model_path: Path to ONNX model file.

        Returns:
            True if loaded successfully.
        """
        if not self.use_embeddings:
            return True

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            # Default model path
            if model_path is None:
                model_path = Path.home() / ".merlya" / "models" / "router.onnx"

            if not model_path.exists():
                logger.warning(f"Model not found: {model_path}")
                return False

            # Load in thread to avoid blocking
            def _load() -> tuple[Any, Any]:
                sess = ort.InferenceSession(str(model_path))
                tok_path = model_path.parent / "tokenizer.json"
                tok = Tokenizer.from_file(str(tok_path)) if tok_path.exists() else None
                return sess, tok

            self._session, self._tokenizer = await asyncio.to_thread(_load)
            logger.debug("Embedding model loaded")
            return True

        except ImportError:
            logger.warning("onnxruntime not installed, using pattern matching")
            self.use_embeddings = False
            return False
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.use_embeddings = False
            return False

    def classify(self, text: str) -> RouterResult:
        """
        Classify user input.

        Args:
            text: User input text.

        Returns:
            RouterResult with mode, tools, and entities.
        """
        text_lower = text.lower()

        # Extract entities
        entities = self._extract_entities(text)

        # Classify mode
        mode, confidence = self._classify_mode(text_lower)

        # Determine active tools
        tools = self._determine_tools(text_lower, entities)

        # Check for delegation to specialized agent
        delegate_to = self._check_delegation(text_lower)

        return RouterResult(
            mode=mode,
            tools=tools,
            entities=entities,
            confidence=confidence,
            delegate_to=delegate_to,
        )

    def _classify_mode(self, text: str) -> tuple[AgentMode, float]:
        """Classify the agent mode."""
        scores: dict[AgentMode, float] = {mode: 0.0 for mode in AgentMode}

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

    def _determine_tools(
        self, text: str, entities: dict[str, list[str]]
    ) -> list[str]:
        """Determine which tools to activate."""
        tools = ["core"]  # Core tools always active

        for tool_category, keywords in TOOL_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                tools.append(tool_category)

        # If hosts mentioned, add system tools
        if entities.get("hosts"):
            if "system" not in tools:
                tools.append("system")

        return tools

    def _extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract entities from text."""
        entities: dict[str, list[str]] = {
            "hosts": [],
            "variables": [],
            "files": [],
        }

        # Extract @mentions (hosts or variables)
        import re

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

    def _check_delegation(self, text: str) -> str | None:
        """Check if should delegate to specialized agent."""
        for agent, keywords in TOOL_KEYWORDS.items():
            if agent in ["docker", "kubernetes"]:
                if any(kw in text for kw in keywords):
                    return agent
        return None


class IntentRouter:
    """
    Intent router with local/LLM classification.

    Routes user input to appropriate agent mode and tools.
    """

    def __init__(self, use_local: bool = True) -> None:
        """
        Initialize router.

        Args:
            use_local: Whether to use local classification.
        """
        self.classifier = IntentClassifier(use_embeddings=use_local)
        self._llm_fallback: Any | None = None

    async def initialize(self) -> None:
        """Initialize the router."""
        await self.classifier.load_model()
        logger.debug("IntentRouter initialized")

    async def route(
        self,
        user_input: str,
        available_agents: list[str] | None = None,
    ) -> RouterResult:
        """
        Route user input.

        Args:
            user_input: User input text.
            available_agents: List of available specialized agents.

        Returns:
            RouterResult with classification.
        """
        result = self.classifier.classify(user_input)

        # Check if delegation is valid
        if result.delegate_to and available_agents:
            if result.delegate_to not in available_agents:
                result.delegate_to = None

        logger.debug(
            f"Routed: mode={result.mode.value}, "
            f"tools={result.tools}, "
            f"delegate={result.delegate_to}"
        )

        return result

    def set_llm_fallback(self, llm: Any) -> None:
        """Set LLM for fallback classification."""
        self._llm_fallback = llm
