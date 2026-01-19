"""
Merlya Router - Intent Classification and Routing.

Classifies user input to determine agent mode and tools.
Uses SmartExtractor with fast LLM model for semantic understanding,
with regex fallback for fast path and when LLM is unavailable.

v0.8.0: Migrated from ONNX to SmartExtractor (fast LLM).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel

from merlya.router.intent_classifier import AgentMode, IntentClassifier
from merlya.router.models import RouterResult
from merlya.router.router_primitives import (
    FAST_PATH_INTENTS,
    FAST_PATH_PATTERNS,
    JUMP_HOST_PATTERNS,
    _LLMClassification,
    extract_json_dict,
    iter_fast_path_patterns,
)

if TYPE_CHECKING:
    from merlya.config import Config
    from merlya.router.smart_extractor import SmartExtractor

# Backward compatibility: tests and older code imported this symbol from classifier.py.
_COMPILED_FAST_PATH = iter_fast_path_patterns()

# Re-export for compatibility
__all__ = [
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
    "AgentMode",
    "IntentClassifier",
    "IntentRouter",
    "RouterResult",
]


class IntentRouter:
    """
    Intent router with SmartExtractor (fast LLM) for semantic understanding.

    Routes user input to appropriate agent mode and tools using:
    1. Fast path detection (regex for simple commands)
    2. SmartExtractor (fast LLM like Haiku) for entity extraction and classification
    3. Fallback to regex patterns when LLM unavailable
    """

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
                logger.debug("🧠 SmartExtractor initialized for semantic extraction")

            self._initialized = True
            logger.debug("🧠 IntentRouter initialized")

    def set_llm_fallback(self, model: str) -> None:
        """
        Set LLM model for fallback classification.

        Args:
            model: LLM model string (e.g., "openai:gpt-4o-mini")
        """
        self._llm_model = model
        logger.debug(f"🧠 LLM fallback set: {model}")

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
        if not self._initialized:
            async with self._init_lock:
                if not self._initialized:
                    await self.initialize()

        # 1. Check for fast path intents first (simple operations)
        fast_path, fast_path_args = self._detect_fast_path(user_input)
        if fast_path:
            logger.debug(f"⚡ Fast path detected: {fast_path}")
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

        # 3. If confidence is low and we have LLM fallback, use it
        if result.confidence < self.classifier.CONFIDENCE_THRESHOLD and self._llm_model:
            llm_result = await self._classify_with_llm(user_input)
            if llm_result:
                # Preserve entities if LLM didn't extract them (LLM often misses custom hostnames)
                if result.entities and not llm_result.entities:
                    llm_result.entities = result.entities
                    logger.debug(
                        "📋 Preserving entities from SmartExtractor (LLM fallback missed them)"
                    )
                result = llm_result

        # Check if delegation is valid
        if result.delegate_to and available_agents and result.delegate_to not in available_agents:
            result.delegate_to = None

        jump_info = f", jump_host={result.jump_host}" if result.jump_host else ""
        logger.debug(
            f"🧠 Routed: mode={result.mode.value}, conf={result.confidence:.2f}, "
            f"tools={result.tools}, delegate={result.delegate_to}{jump_info}"
        )

        return result

    def _validate_identifier(self, name: str) -> bool:
        """Validate that an identifier is safe (hostname, variable name, etc.).

        Prevents path traversal and injection attacks.
        """
        if not name or len(name) > 255:
            return False
        # Must start with alphanumeric, contain only safe chars
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", name):
            return False
        # Reject path traversal attempts
        return ".." not in name

    def _detect_fast_path(self, text: str) -> tuple[str | None, dict[str, str]]:
        """
        Detect fast path intent from user input.

        Args:
            text: User input text.

        Returns:
            Tuple of (intent_name, extracted_args) or (None, {}) if no match.
        """
        text_stripped = text.strip()

        for intent, patterns in iter_fast_path_patterns().items():
            for pattern in patterns:
                match = pattern.search(text_stripped)
                if match:
                    # Extract named groups or positional groups as args
                    args: dict[str, str] = {}
                    if match.groups():
                        target = match.group(1)
                        # P0 Security: Validate identifier before using
                        if not self._validate_identifier(target):
                            logger.warning(f"⚠️ Invalid target identifier: {target[:50]}")
                            continue  # Skip this pattern, try next
                        args["target"] = target
                    return intent, args

        return None, {}

    async def _classify(self, text: str) -> RouterResult:
        """
        Classify user input using SmartExtractor (fast LLM) or pattern matching fallback.

        Args:
            text: User input text.

        Returns:
            RouterResult with mode, tools, and entities.
        """
        text_lower = text.lower()

        # Try SmartExtractor first (fast LLM for semantic understanding)
        if self._smart_extractor:
            try:
                extraction = await self._smart_extractor.extract(text)

                # Convert SmartExtractor result to RouterResult format
                entities: dict[str, list[str]] = {}
                if extraction.entities.hosts:
                    entities["hosts"] = extraction.entities.hosts
                if extraction.entities.services:
                    entities["services"] = extraction.entities.services
                if extraction.entities.paths:
                    entities["paths"] = extraction.entities.paths
                if extraction.entities.ports:
                    entities["ports"] = [str(p) for p in extraction.entities.ports]

                # Map center classification to AgentMode
                center = extraction.intent.center.upper()
                if center == "CHANGE":
                    mode = AgentMode.REMEDIATION
                elif center == "DIAGNOSTIC":
                    mode = AgentMode.DIAGNOSTIC
                else:
                    mode = AgentMode.QUERY

                confidence = extraction.intent.confidence

                # Jump host from extraction or fallback to regex
                jump_host = extraction.entities.jump_host or self._detect_jump_host(text)

                # Determine tools based on entities
                tools = self.classifier.determine_tools(text_lower, entities)

                # Check for delegation
                delegate_to = self.classifier.check_delegation(text_lower)

                logger.debug(
                    f"🎯 SmartExtractor: mode={mode.value}, hosts={entities.get('hosts', [])}, "
                    f"confidence={confidence:.2f}"
                )

                return RouterResult(
                    mode=mode,
                    tools=tools,
                    entities=entities,
                    confidence=confidence,
                    delegate_to=delegate_to,
                    jump_host=jump_host,
                )

            except Exception as e:
                logger.warning(f"⚠️ SmartExtractor failed, falling back to regex: {e}")

        # Fallback: Extract entities using regex
        entities = self.classifier.extract_entities(text)

        # Detect jump host from patterns
        jump_host = self._detect_jump_host(text)
        if jump_host:
            logger.debug(f"🔗 Detected jump host: {jump_host}")

        # Try embedding-based classification (deprecated)
        if self.classifier.model_loaded:
            mode, confidence = await self.classifier.classify_embeddings(text)
        else:
            # Fallback to pattern matching
            mode, confidence = self.classifier.classify_patterns(text_lower)

        # Determine active tools
        tools = self.classifier.determine_tools(text_lower, entities)

        # Check for delegation to specialized agent
        delegate_to = self.classifier.check_delegation(text_lower)

        return RouterResult(
            mode=mode,
            tools=tools,
            entities=entities,
            confidence=confidence,
            delegate_to=delegate_to,
            jump_host=jump_host,
        )

    def _detect_jump_host(self, text: str) -> str | None:
        """
        Detect jump/bastion host from user input.

        Looks for patterns like:
        - "via @ansible" / "via ansible"
        - "through the bastion"
        - "en passant par @jump-host"

        Args:
            text: User input text.

        Returns:
            Jump host name if detected, None otherwise.
        """
        text_lower = text.lower()

        for pattern in JUMP_HOST_PATTERNS:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                jump_host = match.group(1)
                # Filter out common false positives
                if jump_host and jump_host not in ("the", "la", "le", "machine", "host"):
                    return jump_host

        return None

    # Timeout for LLM classification calls (in seconds)
    LLM_CLASSIFICATION_TIMEOUT = 15.0

    async def _classify_with_llm(self, user_input: str) -> RouterResult | None:
        """
        Use LLM for intent classification when embedding confidence is low.

        Args:
            user_input: User input text.

        Returns:
            RouterResult or None if LLM fails.
        """
        if not self._llm_model:
            return None

        try:
            from pydantic_ai import Agent

            logger.debug(f"🧠 LLM classification starting with {self._llm_model}")

            # Create classification prompt
            system_prompt = """You are an intent classifier for an infrastructure management AI.
Classify the user's input into one of these modes:
- diagnostic: Checking status, monitoring, analyzing, listing, viewing
- remediation: Fixing, changing, deploying, configuring, restarting
- query: Asking questions, seeking explanations, learning
- chat: Greetings, thanks, general conversation

Also identify which tool categories are relevant:
- system: CPU, memory, disk, processes, services
- files: File operations, configurations, logs
- security: Ports, firewall, SSH, certificates
- docker: Container operations
- kubernetes: K8s operations
- credentials_required: true/false if auth credentials are needed
- elevation_required: true/false if admin/root is needed

Respond in JSON format:
{"mode": "diagnostic|remediation|query|chat", "tools": ["core", "system", ...], "credentials_required": false, "elevation_required": false, "reasoning": "brief explanation"}"""

            agent = Agent(
                self._llm_model,
                system_prompt=system_prompt,
                output_type=_LLMClassification,
                retries=1,
            )

            # Add timeout to prevent indefinite hangs
            response = await asyncio.wait_for(
                agent.run(f"Classify this input: {user_input}"),
                timeout=self.LLM_CLASSIFICATION_TIMEOUT,
            )
            logger.debug("🧠 LLM classification completed")
            return self._parse_llm_response(response, user_input)

        except TimeoutError:
            logger.warning(
                f"⚠️ LLM classification timed out after {self.LLM_CLASSIFICATION_TIMEOUT}s"
            )
            return None
        except Exception as e:
            logger.warning(f"⚠️ LLM classification failed: {e}")
            return None

    def _parse_llm_response(self, response: object, user_input: str) -> RouterResult | None:
        """Parse LLM classification response."""
        # Security limit for LLM response size
        MAX_LLM_RESPONSE_SIZE = 100_000  # 100KB

        try:
            raw_output = getattr(response, "output", None)
            raw_data = getattr(response, "data", None)
            raw: object | None

            # Prefer explicit payloads (tests/mocks often have .data set while .output is a MagicMock).
            if isinstance(raw_data, (BaseModel, dict, str)):
                raw = raw_data
            elif isinstance(raw_output, (BaseModel, dict, str)):
                raw = raw_output
            else:
                raw = raw_output if raw_output is not None else raw_data
            data: dict[str, Any] | None = None

            if isinstance(raw, BaseModel):
                data = raw.model_dump()
            elif isinstance(raw, dict):
                data = raw
            elif raw is not None:
                raw_str = str(raw)
                # P0 Security: Validate size before parsing
                if len(raw_str) > MAX_LLM_RESPONSE_SIZE:
                    logger.warning(f"⚠️ LLM response too large: {len(raw_str)} bytes")
                    return None
                data = extract_json_dict(raw_str) or json.loads(raw_str)
            else:
                raw_str = str(response)
                if len(raw_str) > MAX_LLM_RESPONSE_SIZE:
                    logger.warning(f"⚠️ LLM response too large: {len(raw_str)} bytes")
                    return None
                data = extract_json_dict(raw_str) or json.loads(raw_str)

            if data is None:
                return None

            # Validate mode before creating enum
            mode_str = data.get("mode", "chat")
            try:
                mode = AgentMode(mode_str)
            except ValueError:
                logger.warning(f"⚠️ Invalid mode from LLM: {mode_str}, defaulting to CHAT")
                mode = AgentMode.CHAT

            tools = data.get("tools", ["core"])
            reasoning = data.get("reasoning")
            credentials_required = bool(data.get("credentials_required", False))
            elevation_required = bool(data.get("elevation_required", False))

            # Re-extract entities and jump host
            entities = self.classifier.extract_entities(user_input)
            delegate_to = self.classifier.check_delegation(user_input.lower())
            jump_host = self._detect_jump_host(user_input)

            return RouterResult(
                mode=mode,
                tools=tools,
                entities=entities,
                confidence=0.9,  # LLM classifications are generally reliable
                delegate_to=delegate_to,
                reasoning=reasoning,
                credentials_required=credentials_required,
                elevation_required=elevation_required,
                jump_host=jump_host,
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"⚠️ Failed to parse LLM response: {e}")
            return None

    @property
    def model_loaded(self) -> bool:
        """Return True if the classifier model is loaded."""
        return self.classifier.model_loaded

    @property
    def embedding_dim(self) -> int | None:
        """Return embedding dimension if available."""
        return self.classifier.embedding_dim
