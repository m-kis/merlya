"""
Merlya Router - Intent Classification and Routing.

Classifies user input to determine agent mode and tools.
Uses SmartExtractor with fast LLM model for semantic understanding,
with regex fallback for fast path and when LLM is unavailable.

v0.8.0: Migrated from ONNX to SmartExtractor (fast LLM).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from merlya.router.intent_classifier import AgentMode
from merlya.router.models import RouterResult
from merlya.router.router_primitives import FAST_PATH_INTENTS, FAST_PATH_PATTERNS

from .core import classify_input, handle_llm_fallback, handle_skill_matching
from .heuristic import detect_fast_path, detect_jump_host, validate_identifier
from .llm_classifier import (
    LLM_CLASSIFICATION_TIMEOUT,
    classify_with_llm,
    match_skill_embeddings,
    match_skill_with_llm,
    parse_llm_response,
)
from .models import IntentClassifier
from .patterns import _COMPILED_FAST_PATH

if TYPE_CHECKING:
    from merlya.config import Config
    from merlya.router.smart_extractor import SmartExtractor


class IntentRouter:
    """
    Intent router with SmartExtractor (fast LLM) for semantic understanding.

    Routes user input to appropriate agent mode and tools using:
    1. Fast path detection (regex for simple commands)
    2. SmartExtractor (fast LLM like Haiku) for entity extraction and classification
    3. Fallback to regex patterns when LLM unavailable
    """

    # Timeout for LLM classification calls (in seconds)
    LLM_CLASSIFICATION_TIMEOUT = LLM_CLASSIFICATION_TIMEOUT

    def __init__(
        self,
        use_local: bool = True,
        model_id: str | None = None,
        tier: str | None = None,
        config: Config | None = None,
    ) -> None:
        """
        Initialize router.

        Args:
            use_local: Whether to use local embedding model (deprecated, kept for compat).
            model_id: Model ID (deprecated, kept for compat).
            tier: Model tier (deprecated, kept for compat).
            config: Merlya configuration for SmartExtractor.
        """
        # Legacy classifier (regex-based fallback)
        self.classifier = IntentClassifier(
            use_embeddings=use_local,
            model_id=model_id,
            tier=tier,
        )
        self._llm_model: str | None = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

        # SmartExtractor (fast LLM for semantic understanding)
        self._config = config
        self._smart_extractor: SmartExtractor | None = None
        self._use_smart_extraction = config is not None

    async def initialize(self) -> None:
        """Initialize the router (load SmartExtractor and legacy classifier)."""
        if not self._initialized:
            await self.classifier.load_model()

            # Initialize SmartExtractor if config is available
            if self._config and self._use_smart_extraction:
                from merlya.router.smart_extractor import SmartExtractor

                self._smart_extractor = SmartExtractor(self._config)
                logger.debug("SmartExtractor initialized for semantic extraction")

            self._initialized = True
            logger.debug("IntentRouter initialized")

    def set_llm_fallback(self, model: str) -> None:
        """
        Set LLM model for fallback classification.

        Args:
            model: LLM model string (e.g., "openai:gpt-4o-mini")
        """
        self._llm_model = model
        logger.debug(f"LLM fallback set: {model}")

    async def route(
        self,
        user_input: str,
        available_agents: list[str] | None = None,
        check_skills: bool = True,
    ) -> RouterResult:
        """
        Route user input.

        Args:
            user_input: User input text.
            available_agents: List of available specialized agents.
            check_skills: Whether to check for skill matches.

        Returns:
            RouterResult with classification.
        """
        if not self._initialized:
            async with self._init_lock:
                if not self._initialized:
                    await self.initialize()

        # 1. Check for fast path intents first (simple operations)
        fast_path, fast_path_args = self._detect_fast_path(user_input)
        if fast_path:
            logger.debug(f"Fast path detected: {fast_path}")
            # Still get entities for context
            entities = self.classifier.extract_entities(user_input)
            return RouterResult(
                mode=AgentMode.QUERY,
                tools=["core"],
                entities=entities,
                confidence=1.0,
                fast_path=fast_path,
                fast_path_args=fast_path_args,
            )

        # 2. Classify input using embeddings/patterns
        result = await self._classify(user_input)

        # 3. Check for skill matches using semantic embeddings (preferred)
        # Skip skill matching if user prefixes with "!" (forces agent mode)
        skip_skills = user_input.strip().startswith("!")
        if skip_skills:
            user_input = user_input.strip()[1:].strip()  # Remove "!" prefix
            logger.debug("Skill matching bypassed (! prefix)")

        result = await handle_skill_matching(
            user_input, result, self.classifier, self._llm_model, check_skills, skip_skills
        )

        # 4. If confidence is low and we have LLM fallback, use it
        result = await handle_llm_fallback(
            user_input, result, self.classifier, self._llm_model, self._detect_jump_host
        )

        # Check if delegation is valid
        if result.delegate_to and available_agents and result.delegate_to not in available_agents:
            result.delegate_to = None

        jump_info = f", jump_host={result.jump_host}" if result.jump_host else ""
        skill_info = f", skill={result.skill_match}" if result.skill_match else ""
        logger.debug(
            f"Routed: mode={result.mode.value}, conf={result.confidence:.2f}, "
            f"tools={result.tools}, delegate={result.delegate_to}{jump_info}{skill_info}"
        )

        return result

    def _validate_identifier(self, name: str) -> bool:
        """Validate that an identifier is safe (hostname, variable name, etc.)."""
        return validate_identifier(name)

    def _detect_fast_path(self, text: str) -> tuple[str | None, dict[str, str]]:
        """Detect fast path intent from user input."""
        return detect_fast_path(text)

    def _detect_jump_host(self, text: str) -> str | None:
        """Detect jump/bastion host from user input."""
        return detect_jump_host(text)

    async def _match_skill_embeddings(self, user_input: str) -> tuple[str | None, float]:
        """Match user input against registered skills using semantic embeddings."""
        return await match_skill_embeddings(self.classifier, user_input)

    async def _match_skill_with_llm(self, user_input: str) -> tuple[str | None, float]:
        """Match user input against registered skills using LLM."""
        return await match_skill_with_llm(self._llm_model, user_input)

    def _match_skill(self, user_input: str) -> tuple[str | None, float]:
        """Match user input against registered skills (regex fallback - DEPRECATED)."""
        try:
            from merlya.skills.registry import get_registry

            registry = get_registry()
            matches = registry.match_intent(user_input)

            if matches:
                skill, confidence = matches[0]
                return skill.name, confidence

        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Skill matching error: {e}")

        return None, 0.0

    async def _classify(self, text: str) -> RouterResult:
        """Classify user input using SmartExtractor or pattern matching fallback."""
        return await classify_input(text, self._smart_extractor, self.classifier)

    async def _classify_with_llm(self, user_input: str) -> RouterResult | None:
        """Use LLM for intent classification when embedding confidence is low."""
        return await classify_with_llm(
            self._llm_model,
            user_input,
            self.classifier,
            self._detect_jump_host,
        )

    def _parse_llm_response(self, response: object, user_input: str) -> RouterResult | None:
        """Parse LLM classification response."""
        return parse_llm_response(response, user_input, self.classifier, self._detect_jump_host)

    @property
    def model_loaded(self) -> bool:
        """Return True if the classifier model is loaded."""
        return self.classifier.model_loaded

    @property
    def embedding_dim(self) -> int | None:
        """Return embedding dimension if available."""
        return self.classifier.embedding_dim


# Re-export for compatibility
__all__ = [
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    "_COMPILED_FAST_PATH",
    "AgentMode",
    "IntentClassifier",
    "IntentRouter",
    "RouterResult",
]
