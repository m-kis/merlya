"""
Merlya Router - Intent Classification and Routing.

Classifies user input to determine agent mode and tools.
Uses local ONNX embedding model with LLM fallback for ambiguous cases.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loguru import logger
from pydantic import BaseModel

from merlya.router.intent_classifier import AgentMode, IntentClassifier
from merlya.router.models import RouterResult
from merlya.router.router_primitives import (
    FAST_PATH_INTENTS,
    FAST_PATH_PATTERNS,
    JUMP_HOST_PATTERNS,
    _LLMClassification,
    _LLMSkillMatch,
    extract_json_dict,
    iter_fast_path_patterns,
)

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
        self._init_lock = asyncio.Lock()

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

        # 3. Check for skill matches using semantic embeddings (preferred)
        # Skip skill matching if user prefixes with "!" (forces agent mode)
        skip_skills = user_input.strip().startswith("!")
        if skip_skills:
            user_input = user_input.strip()[1:].strip()  # Remove "!" prefix
            logger.debug("🚫 Skill matching bypassed (! prefix)")

        # SKILL AUTO-MATCHING DISABLED
        # Skills caused too many false positives (e.g., "config cloudflared" -> service_check at 0.88)
        # The main LLM agent handles all requests better with full tool access.
        # Skills are still available via explicit invocation: /skill run <name> @hosts
        #
        # To re-enable, set check_skills=True and uncomment below:
        _ = check_skills  # Suppress unused variable warning
        if False and check_skills and not skip_skills:  # noqa: SIM223
            try:
                # Only use semantic embeddings for skill matching
                # Regex fallback is DISABLED - it causes too many false positives
                if self.classifier.model_loaded:
                    skill_match, skill_confidence = await self._match_skill_embeddings(user_input)

                    # Log ALL matches for debugging (even below threshold)
                    if skill_match:
                        logger.info(f"🎯 Skill candidate: {skill_match} ({skill_confidence:.2f})")

                    # Require higher confidence (0.88) to avoid false positives
                    # Lower values cause skills like service_check to trigger for config queries
                    # Example: "config cloudflared" scores 0.87 for service_check (false positive)
                    if skill_match and skill_confidence >= 0.88:
                        result.skill_match = skill_match
                        result.skill_confidence = skill_confidence
                        logger.info(f"✅ Skill activated: {skill_match} ({skill_confidence:.2f})")
                elif self._llm_model:
                    # ONNX not loaded but LLM fallback is configured
                    # Use LLM to match skills (slower but accurate)
                    skill_match, skill_confidence = await self._match_skill_with_llm(user_input)
                    if skill_match and skill_confidence >= 0.7:
                        result.skill_match = skill_match
                        result.skill_confidence = skill_confidence
                        logger.debug(
                            f"🎯 Skill match (LLM): {skill_match} ({skill_confidence:.2f})"
                        )
                else:
                    # ONNX not loaded and no LLM fallback - skip skill matching entirely
                    # This prevents regex patterns from causing false matches
                    logger.debug("⚠️ Skill matching disabled - ONNX not loaded, no LLM fallback")
            except Exception as e:
                logger.warning(f"⚠️ Skill matching failed: {e}")

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

    async def _match_skill_embeddings(self, user_input: str) -> tuple[str | None, float]:
        """
        Match user input against registered skills using semantic embeddings.

        This is the preferred method - uses ONNX embeddings for semantic understanding.

        Args:
            user_input: User input text.

        Returns:
            Tuple of (skill_name, confidence) or (None, 0.0).
        """
        if self.classifier.model_loaded:
            skill_name, confidence = await self.classifier.get_best_skill_match(user_input)  # type: ignore[attr-defined]
            if skill_name:
                return skill_name, confidence
        return None, 0.0

    async def _match_skill_with_llm(self, user_input: str) -> tuple[str | None, float]:
        """
        Match user input against registered skills using LLM.

        This is the fallback method when ONNX is not available.
        Slower but accurate for skill matching.

        Args:
            user_input: User input text.

        Returns:
            Tuple of (skill_name, confidence) or (None, 0.0).
        """
        if not self._llm_model:
            return None, 0.0

        try:
            from pydantic_ai import Agent

            from merlya.skills.registry import get_registry

            registry = get_registry()
            skills = registry.get_all()

            if not skills:
                return None, 0.0

            # Build skills description for LLM
            skills_info = []
            for skill in skills:
                skills_info.append(f"- {skill.name}: {skill.description}")

            skills_list = "\n".join(skills_info)

            system_prompt = f"""You are a skill matcher. Given a user request and a list of available skills,
determine if any skill matches the request.

Available skills:
{skills_list}

Respond in JSON format:
{{"skill": "skill_name or null", "confidence": 0.0-1.0, "reason": "brief explanation"}}

Rules:
- Only match if the request clearly fits the skill's purpose
- Return null if no skill matches or if it's a general question
- Confidence should be 0.7+ only for clear matches
- Don't match skills for questions about configuration or setup"""

            agent = Agent(
                self._llm_model,
                system_prompt=system_prompt,
                output_type=_LLMSkillMatch,
                retries=1,
            )

            run_result = await agent.run(f"Does any skill match this request? '{user_input}'")
            match = run_result.output
            skill_name = match.skill
            confidence = float(match.confidence)

            if skill_name and confidence >= 0.5:
                # Verify skill exists
                if registry.get(skill_name):
                    logger.debug(
                        f"🎯 LLM skill match: {skill_name} ({confidence:.2f}) - {match.reason or ''}"
                    )
                    return skill_name, confidence
                else:
                    logger.warning(f"⚠️ LLM matched non-existent skill: {skill_name}")

        except Exception as e:
            logger.warning(f"⚠️ LLM skill matching failed: {e}")

        return None, 0.0

    def _match_skill(self, user_input: str) -> tuple[str | None, float]:
        """
        Match user input against registered skills (regex fallback - DEPRECATED).

        NOTE: This method is deprecated. Use _match_skill_embeddings() instead.
        Kept for backward compatibility when ONNX model is not loaded.

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
                output_type=_LLMClassification,
                retries=1,
            )

            response = await agent.run(f"Classify this input: {user_input}")
            return self._parse_llm_response(response, user_input)

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
