"""
AI-based Triage Classifier.

Uses a fast LLM (haiku/mini) for intelligent intent and priority classification.
Falls back to keyword-based classification if LLM is unavailable.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from athena_ai.utils.logger import logger

from .priority import Intent, Priority, PriorityResult
from .signals import SignalDetector

# Classification prompt - kept minimal for speed
CLASSIFICATION_PROMPT = """Classify this infrastructure/DevOps request.

Request: "{query}"

Respond with JSON only:
{{"intent": "query|action|analysis", "priority": "P0|P1|P2|P3", "reasoning": "brief reason"}}

Intent guide:
- query: Information request (list, show, what is, tell me)
- action: Execute/modify (restart, check, install, fix, deploy)
- analysis: Investigation (why, diagnose, troubleshoot, analyze logs)

Priority guide:
- P0: Production down, data loss, security breach
- P1: Service degraded, performance issues, urgent
- P2: Non-critical issues, warnings
- P3: Normal requests, maintenance, questions"""


@dataclass
class AIClassificationResult:
    """Result from AI classification."""
    intent: Intent
    priority: Priority
    reasoning: str
    from_cache: bool = False


class AITriageClassifier:
    """
    AI-powered triage classifier using LLM.

    Features:
    - Fast LLM classification (haiku/mini)
    - In-memory cache for repeated queries
    - Keyword fallback when LLM unavailable
    - Configurable timeout
    """

    def __init__(
        self,
        model: str = "haiku",
        timeout: float = 5.0,
        cache_size: int = 500,
        use_fallback: bool = True,
    ):
        """
        Initialize AI classifier.

        Args:
            model: LLM model to use (haiku, sonnet, gpt-4o-mini)
            timeout: Max seconds to wait for LLM response
            cache_size: Max cached classifications
            use_fallback: Whether to use keyword fallback on LLM failure
        """
        self._model = model
        self._timeout = timeout
        self._cache: Dict[str, AIClassificationResult] = {}
        self._cache_order: list = []
        self._cache_size = cache_size
        self._use_fallback = use_fallback
        self._signal_detector = SignalDetector() if use_fallback else None
        self._llm_client = None

    def _get_cache_key(self, query: str) -> str:
        """Generate cache key from query."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def _get_from_cache(self, query: str) -> Optional[AIClassificationResult]:
        """Get cached classification result."""
        key = self._get_cache_key(query)
        if key in self._cache:
            result = self._cache[key]
            result.from_cache = True
            return result
        return None

    def _add_to_cache(self, query: str, result: AIClassificationResult) -> None:
        """Add result to cache with LRU eviction."""
        key = self._get_cache_key(query)

        if key in self._cache:
            self._cache_order.remove(key)

        self._cache[key] = result
        self._cache_order.append(key)

        # Evict oldest if over size
        while len(self._cache) > self._cache_size:
            oldest = self._cache_order.pop(0)
            del self._cache[oldest]

    async def _call_llm(self, query: str) -> Optional[Dict[str, Any]]:
        """Call LLM for classification."""
        try:
            # Lazy import to avoid circular deps
            from litellm import acompletion

            prompt = CLASSIFICATION_PROMPT.format(query=query[:500])  # Limit query length

            response = await acompletion(
                model=self._resolve_model(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=100,
                timeout=self._timeout,
            )

            content = response.choices[0].message.content.strip()

            # Parse JSON response
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            return json.loads(content)

        except Exception as e:
            logger.debug(f"LLM classification failed: {e}")
            return None

    def _resolve_model(self) -> str:
        """Resolve model name to full model ID."""
        model_map = {
            "haiku": "anthropic/claude-3-haiku-20240307",
            "sonnet": "anthropic/claude-sonnet-4-20250514",
            "gpt-mini": "gpt-4o-mini",
            "gpt4": "gpt-4o",
        }
        return model_map.get(self._model, self._model)

    def _parse_llm_response(self, response: Dict[str, Any]) -> Optional[AIClassificationResult]:
        """Parse and validate LLM response."""
        try:
            intent_str = response.get("intent", "action").lower()
            priority_str = response.get("priority", "P3").upper()
            reasoning = response.get("reasoning", "")

            # Map to enums
            intent_map = {
                "query": Intent.QUERY,
                "action": Intent.ACTION,
                "analysis": Intent.ANALYSIS,
            }
            intent = intent_map.get(intent_str, Intent.ACTION)

            # Parse priority
            if priority_str in ("P0", "P1", "P2", "P3"):
                priority = Priority[priority_str]
            else:
                priority = Priority.P3

            return AIClassificationResult(
                intent=intent,
                priority=priority,
                reasoning=reasoning,
            )

        except Exception as e:
            logger.debug(f"Failed to parse LLM response: {e}")
            return None

    def _fallback_classify(self, query: str) -> AIClassificationResult:
        """Fallback to keyword-based classification."""
        if not self._signal_detector:
            return AIClassificationResult(
                intent=Intent.ACTION,
                priority=Priority.P3,
                reasoning="Default classification (no fallback)",
            )

        intent, confidence, signals = self._signal_detector.detect_intent(query)
        priority, _, _ = self._signal_detector.detect_keywords(query)

        return AIClassificationResult(
            intent=intent,
            priority=priority,
            reasoning=f"Keyword fallback: {', '.join(signals[:2])}",
        )

    async def classify(
        self,
        query: str,
        skip_cache: bool = False,
    ) -> AIClassificationResult:
        """
        Classify a query using AI.

        Args:
            query: User query to classify
            skip_cache: If True, skip cache lookup

        Returns:
            AIClassificationResult with intent, priority, reasoning
        """
        # Check cache first
        if not skip_cache:
            cached = self._get_from_cache(query)
            if cached:
                return cached

        # Try LLM classification
        llm_response = await self._call_llm(query)

        if llm_response:
            result = self._parse_llm_response(llm_response)
            if result:
                self._add_to_cache(query, result)
                return result

        # Fallback to keywords
        if self._use_fallback:
            result = self._fallback_classify(query)
            self._add_to_cache(query, result)
            return result

        # Last resort default
        return AIClassificationResult(
            intent=Intent.ACTION,
            priority=Priority.P3,
            reasoning="Classification failed",
        )

    def classify_sync(self, query: str, skip_cache: bool = False) -> AIClassificationResult:
        """
        Synchronous classification (uses fallback only).

        For async classification with LLM, use classify() instead.
        """
        if not skip_cache:
            cached = self._get_from_cache(query)
            if cached:
                return cached

        return self._fallback_classify(query)

    def get_stats(self) -> Dict[str, Any]:
        """Get classifier statistics."""
        return {
            "model": self._model,
            "cache_size": len(self._cache),
            "cache_max": self._cache_size,
            "fallback_enabled": self._use_fallback,
        }

    def clear_cache(self) -> None:
        """Clear the classification cache."""
        self._cache.clear()
        self._cache_order.clear()


# Singleton instance
_ai_classifier: Optional[AITriageClassifier] = None


def get_ai_classifier(
    model: str = "haiku",
    force_new: bool = False,
) -> AITriageClassifier:
    """Get or create AI classifier instance."""
    global _ai_classifier

    if force_new or _ai_classifier is None:
        _ai_classifier = AITriageClassifier(model=model)

    return _ai_classifier
