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

from merlya.config.constants import (
    DEFAULT_REQUEST_LIMIT,
    DEFAULT_TOOL_CALLS_LIMIT,
    REQUEST_LIMIT_CHAT,
    REQUEST_LIMIT_DIAGNOSTIC,
    REQUEST_LIMIT_QUERY,
    REQUEST_LIMIT_REMEDIATION,
    TOOL_CALLS_LIMIT_CHAT,
    TOOL_CALLS_LIMIT_DIAGNOSTIC,
    TOOL_CALLS_LIMIT_QUERY,
    TOOL_CALLS_LIMIT_REMEDIATION,
)
from merlya.router.intent_classifier import AgentMode, IntentClassifier

# Fast path intents - operations that can be handled without LLM
# These are simple database queries or direct operations
FAST_PATH_INTENTS = frozenset({
    "host.list",      # List hosts from inventory
    "host.details",   # Get details for a specific host
    "group.list",     # List host groups/tags
    "skill.list",     # List available skills
    "var.list",       # List variables
    "var.get",        # Get a specific variable
})

# Patterns to detect fast path intents
FAST_PATH_PATTERNS: dict[str, list[str]] = {
    "host.list": [
        r"^(?:liste?|show|display|voir)\s+(?:les?\s+)?(?:hosts?|machines?|serveurs?)",
        r"^(?:quels?\s+sont\s+)?(?:mes?\s+)?(?:hosts?|machines?|serveurs?)",
        r"^(?:inventory|inventaire)",
    ],
    "host.details": [
        r"(?:info(?:rmations?)?|details?|détails?)\s+(?:on|about|sur|de)\s+@?(\w[\w.-]*)",
        r"^@(\w[\w.-]*)\s*$",  # Just a host mention
    ],
    "group.list": [
        r"^(?:liste?|show)\s+(?:les?\s+)?(?:groups?|groupes?|tags?)",
        r"^(?:quels?\s+sont\s+)?(?:mes?\s+)?(?:groups?|groupes?)",
    ],
    "skill.list": [
        r"^(?:liste?|show)\s+(?:les?\s+)?skills?",
        r"^(?:quelles?\s+skills?|what\s+skills?)",
    ],
    "var.list": [
        r"^(?:liste?|show)\s+(?:les?\s+)?(?:variables?|vars?)",
    ],
    "var.get": [
        r"(?:valeur|value)\s+(?:de|of)\s+@?(\w[\w_.-]*)",
    ],
}

# Mode to tool calls limit mapping
MODE_TOOL_LIMITS: dict[AgentMode, int] = {
    AgentMode.DIAGNOSTIC: TOOL_CALLS_LIMIT_DIAGNOSTIC,
    AgentMode.REMEDIATION: TOOL_CALLS_LIMIT_REMEDIATION,
    AgentMode.QUERY: TOOL_CALLS_LIMIT_QUERY,
    AgentMode.CHAT: TOOL_CALLS_LIMIT_CHAT,
}

# Mode to request limit mapping
MODE_REQUEST_LIMITS: dict[AgentMode, int] = {
    AgentMode.DIAGNOSTIC: REQUEST_LIMIT_DIAGNOSTIC,
    AgentMode.REMEDIATION: REQUEST_LIMIT_REMEDIATION,
    AgentMode.QUERY: REQUEST_LIMIT_QUERY,
    AgentMode.CHAT: REQUEST_LIMIT_CHAT,
}

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
__all__ = [
    "AgentMode",
    "IntentClassifier",
    "IntentRouter",
    "RouterResult",
    "FAST_PATH_INTENTS",
    "FAST_PATH_PATTERNS",
]

# Pre-compiled fast path patterns for performance
_COMPILED_FAST_PATH: dict[str, list[re.Pattern[str]]] = {}


def _compile_fast_path_patterns() -> None:
    """Compile fast path patterns once at import time."""
    global _COMPILED_FAST_PATH
    if _COMPILED_FAST_PATH:
        return
    for intent, patterns in FAST_PATH_PATTERNS.items():
        _COMPILED_FAST_PATH[intent] = [
            re.compile(p, re.IGNORECASE) for p in patterns
        ]


# Compile patterns at module load
_compile_fast_path_patterns()


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
    fast_path: str | None = None  # Fast path intent if detected (e.g., "host.list")
    fast_path_args: dict[str, str] = field(default_factory=dict)  # Args extracted from pattern
    skill_match: str | None = None  # Matched skill name if detected
    skill_confidence: float = 0.0  # Confidence of skill match

    @property
    def is_fast_path(self) -> bool:
        """Check if this is a fast path intent."""
        return self.fast_path is not None

    @property
    def is_skill_match(self) -> bool:
        """Check if a skill was matched with sufficient confidence."""
        return self.skill_match is not None and self.skill_confidence >= 0.5

    @property
    def tool_calls_limit(self) -> int:
        """Get dynamic tool calls limit based on task mode."""
        return MODE_TOOL_LIMITS.get(self.mode, DEFAULT_TOOL_CALLS_LIMIT)

    @property
    def request_limit(self) -> int:
        """Get dynamic request limit based on task mode."""
        return MODE_REQUEST_LIMITS.get(self.mode, DEFAULT_REQUEST_LIMIT)


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
        # Ensure initialized
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

        # 3. Check for skill matches
        if check_skills:
            skill_match, skill_confidence = self._match_skill(user_input)
            if skill_match and skill_confidence >= 0.5:
                result.skill_match = skill_match
                result.skill_confidence = skill_confidence
                logger.debug(f"🎯 Skill match: {skill_match} ({skill_confidence:.2f})")

        # 4. If confidence is low and we have LLM fallback, use it
        if result.confidence < self.classifier.CONFIDENCE_THRESHOLD and self._llm_model:
            llm_result = await self._classify_with_llm(user_input)
            if llm_result:
                # Preserve skill match from earlier
                if result.skill_match:
                    llm_result.skill_match = result.skill_match
                    llm_result.skill_confidence = result.skill_confidence
                result = llm_result

        # Check if delegation is valid
        if result.delegate_to and available_agents and result.delegate_to not in available_agents:
            result.delegate_to = None

        jump_info = f", jump_host={result.jump_host}" if result.jump_host else ""
        skill_info = f", skill={result.skill_match}" if result.skill_match else ""
        logger.debug(
            f"🧠 Routed: mode={result.mode.value}, conf={result.confidence:.2f}, "
            f"tools={result.tools}, delegate={result.delegate_to}{jump_info}{skill_info}"
        )

        return result

    def _detect_fast_path(self, text: str) -> tuple[str | None, dict[str, str]]:
        """
        Detect fast path intent from user input.

        Args:
            text: User input text.

        Returns:
            Tuple of (intent_name, extracted_args) or (None, {}) if no match.
        """
        text_stripped = text.strip()

        for intent, patterns in _COMPILED_FAST_PATH.items():
            for pattern in patterns:
                match = pattern.search(text_stripped)
                if match:
                    # Extract named groups or positional groups as args
                    args: dict[str, str] = {}
                    if match.groups():
                        # Use first captured group as target
                        args["target"] = match.group(1)
                    return intent, args

        return None, {}

    def _match_skill(self, user_input: str) -> tuple[str | None, float]:
        """
        Match user input against registered skills.

        Args:
            user_input: User input text.

        Returns:
            Tuple of (skill_name, confidence) or (None, 0.0).
        """
        try:
            from merlya.skills.registry import get_registry

            registry = get_registry()
            matches = registry.match_intent(user_input)

            if matches:
                # Return best match
                skill, confidence = matches[0]
                return skill.name, confidence

        except ImportError:
            # Skills module not available
            pass
        except Exception as e:
            logger.debug(f"Skill matching error: {e}")

        return None, 0.0

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
