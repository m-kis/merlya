"""
Merlya Router - Center Classifier.

Classifies user intent to DIAGNOSTIC or CHANGE center.
Uses pattern matching with optional mini-LLM fallback.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, Field

from merlya.centers.base import CenterMode

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class CenterClassification(BaseModel):
    """Result of center classification."""

    center: CenterMode
    confidence: float = Field(ge=0.0, le=1.0)
    clarification_needed: bool = False
    suggested_prompt: str | None = None
    reasoning: str | None = None


# Patterns that clearly indicate DIAGNOSTIC (read-only) intent
DIAGNOSTIC_PATTERNS = [
    # Status/Check
    r"\b(check|status|état|verify|vérifier)\b.*\b(disk|disque|memory|mémoire|cpu|service|process|connexion)\b",
    r"\bcheck\s+(on|the|status|if)\b",
    r"\b(what|quel|quels|quelle)\s+(is|are|est|sont)\b",
    r"\b(show|voir|afficher|display|list|lister)\s+(me|moi)?\s*(the|le|la|les)?\s*",
    r"\b(get|obtenir)\s+(info|information|status|état)\b",
    # Monitoring
    r"\b(monitor|surveiller|watch|observer)\b",
    r"\b(analyze|analyser|investigate|enquêter)\b",
    r"\b(look|regarder)\s+(at|into)\b",
    # Logs/Debug
    r"\b(logs?|journaux?)\b",
    r"\b(tail|grep|search|chercher)\s+",
    r"\b(debug|diagnose|diagnostiquer)\b",
    # Questions
    r"^(what|why|how|when|where|who|quel|pourquoi|comment|quand|où|qui)\b",
    r"\?$",
    # Read operations
    r"\b(read|lire|view|voir|cat|head|tail)\s+",
    r"\b(disk usage|espace disque|memory usage|utilisation mémoire)\b",
    r"\b(uptime|load|charge)\b",
    r"\b(list|lister)\s+(hosts?|hôtes?|servers?|serveurs?|processes?|services?)\b",
]

# Patterns that clearly indicate CHANGE (write/mutation) intent
CHANGE_PATTERNS = [
    # Restart/Start/Stop - more flexible patterns
    r"\b(restart|redémarrer|reboot|relancer)\b",
    r"\b(stop|arrêter|stopper)\s+",
    r"\b(stop|arrêter|stopper)\b.*\b(service|process|container|pod|database|db)\b",
    r"\b(kill|tuer)\s+",
    r"\b(start|démarrer|lancer)\s+",
    r"\b(start|démarrer|lancer)\b.*\b(service|process|container|pod)\b",
    # Fix/Repair
    r"\b(fix|réparer|repair|corriger|resolve|résoudre)\b",
    r"\b(update|mettre à jour|upgrade|améliorer)\b",
    # Deploy/Install
    r"\b(deploy|déployer|install|installer)\b",
    r"\b(configure|configurer|setup|paramétrer)\b",
    # Modify
    r"\b(change|changer|modify|modifier|edit|éditer)\b",
    r"\b(create|créer)\s+",
    r"\b(add|ajouter)\s+(a|an|un|une|new|nouveau|nouvelle)?\s*\w+",
    r"\b(delete|supprimer|remove|retirer)\s+",
    # Scale/Resize
    r"\b(scale|redimensionner|resize)\b",
    r"\b(increase|augmenter|decrease|diminuer)\s+(the|le|la)?\s*(replicas?|instances?|capacity|capacité)",
    # Rollback
    r"\b(rollback|revenir|revert|annuler)\b",
    # Package management
    r"\b(apt|yum|dnf|pip|npm)\s+(install|remove|update|upgrade)\b",
    # Infrastructure
    r"\b(terraform|ansible)\s+(apply|run|execute)\b",
]

# Compiled patterns for efficiency
_DIAGNOSTIC_COMPILED = [re.compile(p, re.IGNORECASE) for p in DIAGNOSTIC_PATTERNS]
_CHANGE_COMPILED = [re.compile(p, re.IGNORECASE) for p in CHANGE_PATTERNS]


class CenterClassifier:
    """
    Classifier for routing between DIAGNOSTIC and CHANGE centers.

    Uses pattern matching with optional LLM fallback for ambiguous cases.
    """

    CONFIDENCE_THRESHOLD = 0.7
    LLM_TIMEOUT = 10.0

    def __init__(self, ctx: SharedContext | None = None):
        """
        Initialize classifier.

        Args:
            ctx: Optional shared context for LLM access.
        """
        self._ctx = ctx

    async def classify(self, user_input: str) -> CenterClassification:
        """
        Classify user intent to DIAGNOSTIC or CHANGE.

        Args:
            user_input: User's request text.

        Returns:
            CenterClassification with center, confidence, and reasoning.
        """
        text = user_input.strip()

        # Try pattern-based classification first
        result = self._classify_patterns(text)

        # If confidence is below threshold, try LLM fallback
        if result.confidence < self.CONFIDENCE_THRESHOLD:
            llm_result = await self._classify_with_llm(text)
            if llm_result and llm_result.confidence > result.confidence:
                result = llm_result

        # If still low confidence, mark as needing clarification
        if result.confidence < self.CONFIDENCE_THRESHOLD:
            result.clarification_needed = True
            result.suggested_prompt = self._generate_clarification_prompt(text, result)

        logger.debug(
            f"🎯 Center classification: {result.center.value} "
            f"(conf={result.confidence:.2f}, clarify={result.clarification_needed})"
        )

        return result

    def _classify_patterns(self, text: str) -> CenterClassification:
        """
        Classify using pattern matching.

        Args:
            text: User input text.

        Returns:
            CenterClassification from patterns.
        """
        diagnostic_score = 0
        change_score = 0

        # Count diagnostic pattern matches
        for pattern in _DIAGNOSTIC_COMPILED:
            if pattern.search(text):
                diagnostic_score += 1

        # Count change pattern matches
        for pattern in _CHANGE_COMPILED:
            if pattern.search(text):
                change_score += 1

        total = diagnostic_score + change_score
        if total == 0:
            # No patterns matched - default to DIAGNOSTIC (safer)
            return CenterClassification(
                center=CenterMode.DIAGNOSTIC,
                confidence=0.3,
                reasoning="No specific patterns matched, defaulting to safe read-only mode",
            )

        # Calculate confidence based on pattern clarity
        if diagnostic_score > change_score:
            center = CenterMode.DIAGNOSTIC
            confidence = min(0.95, 0.5 + (diagnostic_score - change_score) * 0.15)
            reasoning = (
                f"Matched {diagnostic_score} diagnostic patterns vs {change_score} change patterns"
            )
        elif change_score > diagnostic_score:
            center = CenterMode.CHANGE
            confidence = min(0.95, 0.5 + (change_score - diagnostic_score) * 0.15)
            reasoning = (
                f"Matched {change_score} change patterns vs {diagnostic_score} diagnostic patterns"
            )
        else:
            # Tie - default to DIAGNOSTIC (safer)
            center = CenterMode.DIAGNOSTIC
            confidence = 0.5
            reasoning = f"Equal pattern matches ({diagnostic_score} each), defaulting to safe mode"

        return CenterClassification(
            center=center,
            confidence=confidence,
            reasoning=reasoning,
        )

    async def _classify_with_llm(self, text: str) -> CenterClassification | None:
        """
        Use LLM for classification when patterns are ambiguous.

        Args:
            text: User input text.

        Returns:
            CenterClassification or None if LLM unavailable.
        """
        if self._ctx is None:
            return None

        try:
            import asyncio

            from pydantic_ai import Agent

            # Get fast model from context
            model = getattr(self._ctx.config, "get_model", lambda _: None)("fast")
            if not model:
                model = "anthropic:claude-haiku-4-5-20250514"

            system_prompt = """You are an intent classifier for an infrastructure management system.
Classify the user's request into one of two categories:

DIAGNOSTIC: Read-only investigation, checking status, viewing logs, analyzing issues.
No state changes. Examples: "check disk usage", "why is nginx slow", "show service status"

CHANGE: Modifying state, restarting services, deploying, fixing, updating.
Write operations. Examples: "restart nginx", "fix the SSL error", "deploy new version"

Respond in JSON format:
{"category": "DIAGNOSTIC" or "CHANGE", "confidence": 0.0-1.0, "reasoning": "brief explanation"}

Rules:
- Default to DIAGNOSTIC if unsure (safer)
- Questions about status are DIAGNOSTIC
- Questions about "how to fix" are DIAGNOSTIC (just asking, not doing)
- Commands to actually fix/change are CHANGE
- "Check and fix if needed" is CHANGE (includes potential mutation)
"""

            agent = Agent(
                model,
                system_prompt=system_prompt,
                retries=1,
            )

            response = await asyncio.wait_for(
                agent.run(f"Classify: {text}"),
                timeout=self.LLM_TIMEOUT,
            )

            # Parse response
            return self._parse_llm_response(response)

        except Exception as e:
            logger.debug(f"⚠️ LLM classification failed: {e}")
            return None

    def _parse_llm_response(self, response: object) -> CenterClassification | None:
        """Parse LLM response into CenterClassification."""
        import json

        try:
            raw = getattr(response, "data", None) or str(response)
            if hasattr(raw, "model_dump"):
                data = raw.model_dump()
            elif isinstance(raw, dict):
                data = raw
            else:
                # Extract JSON from string
                raw_str = str(raw)
                start = raw_str.find("{")
                end = raw_str.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(raw_str[start:end])
                else:
                    return None

            category = data.get("category", "DIAGNOSTIC").upper()
            center = CenterMode.CHANGE if category == "CHANGE" else CenterMode.DIAGNOSTIC
            confidence = float(data.get("confidence", 0.8))
            reasoning = data.get("reasoning")

            return CenterClassification(
                center=center,
                confidence=confidence,
                reasoning=reasoning,
            )

        except Exception as e:
            logger.debug(f"⚠️ Failed to parse LLM response: {e}")
            return None

    def _generate_clarification_prompt(
        self,
        _text: str,
        result: CenterClassification,
    ) -> str:
        """
        Generate a clarification prompt for ambiguous intent.

        Args:
            _text: Original user input (unused, kept for future use).
            result: Current classification result.

        Returns:
            Clarification question.
        """
        if result.center == CenterMode.DIAGNOSTIC:
            return (
                "I understand you want to investigate something. "
                "Do you want me to just check the status (read-only), "
                "or should I also try to fix any issues I find?"
            )
        else:
            return (
                "This sounds like a change operation. "
                "Should I proceed with making changes, "
                "or would you first like me to just check the current status?"
            )

    def is_definitely_diagnostic(self, text: str) -> bool:
        """
        Quick check if text is definitely a diagnostic request.

        Args:
            text: User input text.

        Returns:
            True if definitely diagnostic (no LLM needed).
        """
        diagnostic_count = sum(1 for p in _DIAGNOSTIC_COMPILED if p.search(text))
        change_count = sum(1 for p in _CHANGE_COMPILED if p.search(text))

        return diagnostic_count >= 2 and change_count == 0

    def is_definitely_change(self, text: str) -> bool:
        """
        Quick check if text is definitely a change request.

        Args:
            text: User input text.

        Returns:
            True if definitely change (no LLM needed).
        """
        diagnostic_count = sum(1 for p in _DIAGNOSTIC_COMPILED if p.search(text))
        change_count = sum(1 for p in _CHANGE_COMPILED if p.search(text))

        return change_count >= 2 and diagnostic_count == 0
