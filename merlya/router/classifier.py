"""
Merlya Router - Intent Classification and Routing.

Classifies user input to determine agent mode and tools.
Uses local ONNX embedding model with LLM fallback for ambiguous cases.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from merlya.router.intent_classifier import AgentMode, IntentClassifier

# Patterns to detect jump host intent (multilingual)
# These patterns look for "via/through/par/depuis + @hostname or hostname"
JUMP_HOST_PATTERNS = [
    # English
    r"\bvia\s+(?:the\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\bthrough\s+(?:the\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\busing\s+(?:the\s+)?(?:bastion|jump\s*host?)\s+@?(\w[\w.-]*)",
    # French
    r"\bvia\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\ben\s+passant\s+par\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\bà\s+travers\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    r"\bdepuis\s+(?:la\s+)?(?:machine\s+)?@?(\w[\w.-]*)",
    # Generic bastion/jump patterns
    r"\bbastion\s*[=:]\s*@?(\w[\w.-]*)",
    r"\bjump\s*host?\s*[=:]\s*@?(\w[\w.-]*)",
]

# Re-export for compatibility
__all__ = ["AgentMode", "IntentClassifier", "IntentRouter", "RouterResult"]


@dataclass
class RouterResult:
    """Result of intent classification."""

    mode: AgentMode
    tools: list[str]
    entities: dict[str, list[str]] = field(default_factory=dict)
    confidence: float = 0.0
    delegate_to: str | None = None
    reasoning: str | None = None  # For LLM fallback explanation
    credentials_required: bool = False
    elevation_required: bool = False
    jump_host: str | None = None  # Detected jump/bastion host for SSH tunneling


class IntentRouter:
    """
    Intent router with local classification and LLM fallback.

    Routes user input to appropriate agent mode and tools.
    """

    def __init__(
        self,
        use_local: bool = True,
        model_id: str | None = None,
        tier: str | None = None,
    ) -> None:
        """
        Initialize router.

        Args:
            use_local: Whether to use local embedding model.
        """
        self.classifier = IntentClassifier(
            use_embeddings=use_local,
            model_id=model_id,
            tier=tier,
        )
        self._llm_model: str | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the router (load embedding model)."""
        if not self._initialized:
            await self.classifier.load_model()
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
        # Ensure initialized
        if not self._initialized:
            await self.initialize()

        # Classify input
        result = await self._classify(user_input)

        # If confidence is low and we have LLM fallback, use it
        if result.confidence < self.classifier.CONFIDENCE_THRESHOLD and self._llm_model:
            llm_result = await self._classify_with_llm(user_input)
            if llm_result:
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

    async def _classify(self, text: str) -> RouterResult:
        """
        Classify user input using embeddings or pattern matching.

        Args:
            text: User input text.

        Returns:
            RouterResult with mode, tools, and entities.
        """
        text_lower = text.lower()

        # Extract entities first
        entities = self.classifier.extract_entities(text)

        # Detect jump host from patterns
        jump_host = self._detect_jump_host(text)
        if jump_host:
            logger.debug(f"🔗 Detected jump host: {jump_host}")

        # Try embedding-based classification
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
            )

            response = await agent.run(f"Classify this input: {user_input}")

            # Parse JSON response
            return self._parse_llm_response(response, user_input)

        except Exception as e:
            logger.warning(f"⚠️ LLM classification failed: {e}")
            return None

    def _parse_llm_response(self, response: object, user_input: str) -> RouterResult | None:
        """Parse LLM classification response."""
        try:
            raw = getattr(response, "data", None)
            if raw is None and hasattr(response, "output"):
                raw = response.output
            if raw is None:
                raw = str(response)

            data = json.loads(str(raw))
            mode = AgentMode(data.get("mode", "chat"))
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
