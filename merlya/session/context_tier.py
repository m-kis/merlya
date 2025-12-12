"""
Merlya Session - Context Tier Predictor.

Automatically determines optimal context tier based on query complexity.
Uses ONNX when available, enriched heuristics as fallback, LLM as last resort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger

# Input size limit to prevent DoS
MAX_INPUT_SIZE = 100_000  # 100KB max for complexity analysis

# Pre-compiled regex patterns for performance and ReDoS prevention
_RE_LOGS = re.compile(r"\b(error|exception|traceback|failed|warning)\b", re.IGNORECASE)
_RE_CODE = re.compile(r"^\s{4,}", re.MULTILINE)
_RE_PATHS = re.compile(r"(/[\w/.-]{1,200}|~/[\w/.-]{0,200})")
_RE_COMMANDS = re.compile(r"\b(run|execute|check|show|list|get|find)\b", re.IGNORECASE)

if TYPE_CHECKING:
    from merlya.router.classifier import RouterResult


class ContextTier(Enum):
    """Context tier levels."""

    MINIMAL = "minimal"  # ~10 messages, 2000 tokens
    STANDARD = "standard"  # ~30 messages, 4000 tokens
    EXTENDED = "extended"  # ~100 messages, 8000 tokens

    @classmethod
    def from_ram_gb(cls, available_gb: float) -> ContextTier:
        """
        Select tier based on available RAM.

        Args:
            available_gb: Available RAM in gigabytes.

        Returns:
            Appropriate ContextTier for the available memory.
        """
        if available_gb >= 8.0:
            return cls.EXTENDED
        elif available_gb >= 4.0:
            return cls.STANDARD
        else:
            return cls.MINIMAL

    @classmethod
    def from_string(cls, value: str | None) -> ContextTier:
        """
        Convert string to ContextTier, with sensible defaults.

        Args:
            value: Tier string (minimal/standard/extended).

        Returns:
            Corresponding ContextTier enum value.
        """
        if not value:
            return cls.STANDARD

        normalized = value.lower().strip()

        try:
            return cls(normalized)
        except ValueError:
            logger.warning(f"Unknown context tier '{value}', defaulting to standard")
            return cls.STANDARD


@dataclass
class TierLimits:
    """Limits for a context tier."""

    max_messages: int
    max_tokens: int
    parser_backend: str
    summarize_threshold: float  # % of max before summarizing


# Tier configuration
TIER_CONFIG = {
    ContextTier.MINIMAL: TierLimits(
        max_messages=10,
        max_tokens=2000,
        parser_backend="lightweight",
        summarize_threshold=0.8,
    ),
    ContextTier.STANDARD: TierLimits(
        max_messages=30,
        max_tokens=4000,
        parser_backend="balanced",
        summarize_threshold=0.75,
    ),
    ContextTier.EXTENDED: TierLimits(
        max_messages=100,
        max_tokens=8000,
        parser_backend="performance",
        summarize_threshold=0.7,
    ),
}


@dataclass
class ComplexityFactors:
    """Factors used for complexity assessment."""

    # Text characteristics
    message_length: int
    line_count: int
    word_count: int

    # Content indicators
    has_logs: bool
    has_code: bool
    has_json: bool
    has_paths: bool
    has_multiple_hosts: bool

    # Router context
    router_confidence: float
    is_incident: bool
    is_remediation: bool
    entities_count: int
    has_jump_host: bool

    # Complexity markers
    question_count: int
    command_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message_length": self.message_length,
            "line_count": self.line_count,
            "word_count": self.word_count,
            "has_logs": self.has_logs,
            "has_code": self.has_code,
            "has_json": self.has_json,
            "has_paths": self.has_paths,
            "has_multiple_hosts": self.has_multiple_hosts,
            "router_confidence": self.router_confidence,
            "is_incident": self.is_incident,
            "is_remediation": self.is_remediation,
            "entities_count": self.entities_count,
            "has_jump_host": self.has_jump_host,
            "question_count": self.question_count,
            "command_count": self.command_count,
        }


class ContextTierPredictor:
    """
    Predicts optimal context tier based on query complexity.

    Uses a cascade approach:
    1. ONNX model if available (most accurate)
    2. Enriched heuristics (fast, no dependencies)
    3. LLM fallback for uncertain cases
    """

    def __init__(
        self,
        onnx_model: Any | None = None,
        fallback_model: str | None = None,
    ) -> None:
        """
        Initialize the predictor.

        Args:
            onnx_model: Optional ONNX complexity model.
            fallback_model: Optional LLM model for uncertain cases.
        """
        self.onnx_model = onnx_model
        self.fallback_model = fallback_model
        logger.debug("🎯 ContextTierPredictor initialized")

    def extract_factors(
        self,
        user_input: str,
        router_result: RouterResult | None = None,
    ) -> ComplexityFactors:
        """
        Extract complexity factors from input.

        Args:
            user_input: User message text.
            router_result: Optional router classification result.

        Returns:
            ComplexityFactors dataclass.
        """
        text = user_input or ""

        # Input size validation - truncate if too large
        if len(text) > MAX_INPUT_SIZE:
            logger.warning(f"Input too large ({len(text)} bytes), truncating to {MAX_INPUT_SIZE}")
            text = text[:MAX_INPUT_SIZE]

        # Text characteristics
        message_length = len(text)
        line_count = text.count("\n") + 1
        word_count = len(text.split())

        # Content detection using pre-compiled patterns
        has_logs = bool(_RE_LOGS.search(text))
        has_code = "```" in text or bool(_RE_CODE.search(text))
        has_json = "{" in text and "}" in text and '"' in text
        has_paths = bool(_RE_PATHS.search(text))

        # Router context (if available)
        router_confidence = 0.5
        is_incident = False
        is_remediation = False
        entities_count = 0
        has_jump_host = False
        has_multiple_hosts = False

        if router_result:
            router_confidence = getattr(router_result, "confidence", 0.5)
            mode = getattr(router_result, "mode", None)
            is_incident = bool(mode and "diagnostic" in str(mode).lower())
            is_remediation = bool(mode and "remediation" in str(mode).lower())

            entities = getattr(router_result, "entities", {})
            if isinstance(entities, dict):
                entities_count = sum(
                    len(v) if isinstance(v, list) else 1 for v in entities.values()
                )
                hosts = entities.get("hosts", [])
                has_multiple_hosts = len(hosts) > 1 if isinstance(hosts, list) else False

            has_jump_host = getattr(router_result, "jump_host", None) is not None

        # Complexity markers
        question_count = text.count("?")
        command_count = len(_RE_COMMANDS.findall(text))

        return ComplexityFactors(
            message_length=message_length,
            line_count=line_count,
            word_count=word_count,
            has_logs=has_logs,
            has_code=has_code,
            has_json=has_json,
            has_paths=has_paths,
            has_multiple_hosts=has_multiple_hosts,
            router_confidence=router_confidence,
            is_incident=is_incident,
            is_remediation=is_remediation,
            entities_count=entities_count,
            has_jump_host=has_jump_host,
            question_count=question_count,
            command_count=command_count,
        )

    def _compute_heuristic_score(self, factors: ComplexityFactors) -> float:
        """
        Compute complexity score from factors.

        Args:
            factors: Extracted complexity factors.

        Returns:
            Score between 0.0 (simple) and 1.0 (complex).
        """
        score = 0.0

        # Length-based scoring (0-0.2)
        if factors.message_length > 2000:
            score += 0.2
        elif factors.message_length > 500:
            score += 0.1
        elif factors.message_length > 100:
            score += 0.05

        # Content type scoring (0-0.3)
        if factors.has_logs:
            score += 0.15
        if factors.has_code:
            score += 0.1
        if factors.has_json:
            score += 0.05

        # Multi-entity scoring (0-0.25)
        if factors.has_multiple_hosts:
            score += 0.15
        if factors.entities_count > 5:
            score += 0.1
        elif factors.entities_count > 2:
            score += 0.05

        # Task type scoring (0-0.15)
        if factors.is_incident:
            score += 0.1
        if factors.is_remediation:
            score += 0.1
        if factors.has_jump_host:
            score += 0.05

        # Complexity markers (0-0.1)
        if factors.question_count > 2:
            score += 0.05
        if factors.command_count > 2:
            score += 0.05

        # Cap at 1.0
        return min(score, 1.0)

    def _score_to_tier(self, score: float) -> ContextTier:
        """
        Convert complexity score to context tier.

        Args:
            score: Complexity score (0.0-1.0).

        Returns:
            Appropriate context tier.
        """
        if score < 0.3:
            return ContextTier.MINIMAL
        elif score < 0.6:
            return ContextTier.STANDARD
        else:
            return ContextTier.EXTENDED

    async def predict(
        self,
        user_input: str,
        router_result: RouterResult | None = None,
    ) -> ContextTier:
        """
        Predict optimal context tier.

        Args:
            user_input: User message text.
            router_result: Optional router classification result.

        Returns:
            Predicted context tier.
        """
        factors = self.extract_factors(user_input, router_result)

        # 1. Try ONNX model if available
        if self.onnx_model and hasattr(self.onnx_model, "predict_complexity"):
            try:
                score = await self.onnx_model.predict_complexity(user_input)
                tier = self._score_to_tier(score)
                logger.debug(f"🎯 Tier predicted by ONNX: {tier.value} (score={score:.2f})")
                return tier
            except (ValueError, TypeError, RuntimeError) as e:
                logger.warning(f"⚠️ ONNX prediction failed ({type(e).__name__}): {e}")
            except Exception as e:
                logger.error(f"⚠️ Unexpected ONNX error ({type(e).__name__}): {e}")

        # 2. Enriched heuristic
        score = self._compute_heuristic_score(factors)

        # 3. If uncertain (0.35-0.55) and fallback LLM available, ask LLM
        if 0.35 < score < 0.55 and self.fallback_model:
            try:
                llm_score = await self._ask_llm_complexity(user_input, factors)
                if llm_score is not None:
                    score = llm_score
                    logger.debug(f"🎯 Tier refined by LLM: score={score:.2f}")
            except (ValueError, TypeError, TimeoutError) as e:
                logger.warning(f"⚠️ LLM complexity check failed ({type(e).__name__}): {e}")
            except Exception as e:
                logger.error(f"⚠️ Unexpected LLM error ({type(e).__name__}): {e}")

        tier = self._score_to_tier(score)
        logger.debug(
            f"🎯 Tier predicted: {tier.value} (score={score:.2f}, factors={len(factors.to_dict())})"
        )

        return tier

    async def _ask_llm_complexity(
        self,
        _user_input: str,
        _factors: ComplexityFactors,
    ) -> float | None:
        """
        Ask LLM to assess complexity for uncertain cases.

        Args:
            user_input: User message.
            factors: Extracted factors.

        Returns:
            Complexity score or None if failed.
        """
        # This would use the fallback_model to ask about complexity
        # For now, return None to use heuristic
        # TODO: Implement LLM fallback when mini-LLM is available
        return None

    def get_tier_limits(self, tier: ContextTier) -> TierLimits:
        """
        Get limits for a context tier.

        Args:
            tier: Context tier.

        Returns:
            TierLimits configuration.
        """
        return TIER_CONFIG[tier]

    def should_summarize(
        self,
        tier: ContextTier,
        current_messages: int,
        current_tokens: int,
    ) -> bool:
        """
        Check if context should be summarized.

        Args:
            tier: Current context tier.
            current_messages: Current message count.
            current_tokens: Current token count.

        Returns:
            True if summarization recommended.
        """
        limits = self.get_tier_limits(tier)
        threshold = limits.summarize_threshold

        # Protect against division by zero
        if limits.max_messages <= 0 or limits.max_tokens <= 0:
            logger.warning("Invalid tier limits (zero or negative), skipping summarization check")
            return False

        messages_pct = current_messages / limits.max_messages
        tokens_pct = current_tokens / limits.max_tokens

        return messages_pct > threshold or tokens_pct > threshold
