from dataclasses import dataclass
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel

from athena_ai.triage import (
    Intent,
    Priority,
    PriorityClassifier,
    PriorityResult,
    SignalDetector,
    describe_behavior,
    get_behavior,
    get_smart_classifier,
)
from athena_ai.triage.ai_classifier import AITriageClassifier, get_ai_classifier
from athena_ai.utils.logger import logger
from athena_ai.utils.verbosity import VerbosityLevel


@dataclass
class TriageContext:
    """Combined triage result with priority and intent."""
    priority_result: PriorityResult
    intent: Intent
    intent_confidence: float
    intent_signals: List[str]
    allowed_tools: Optional[List[str]]  # None = all tools allowed
    query: Optional[str] = None  # Original query for feedback


class IntentParser:
    """Handles intent classification and priority display."""

    def __init__(self, console: Console, verbosity=None, use_ai: bool = True, db_client=None, llm_router=None):
        self.console = console
        self.verbosity = verbosity
        self.classifier = PriorityClassifier()
        self.signal_detector = SignalDetector()
        self._use_ai = use_ai
        self._ai_classifier: Optional[AITriageClassifier] = None
        self._smart_classifier = None
        self._db_client = db_client
        self._llm_router = llm_router
        self._last_query: Optional[str] = None  # Track for feedback

        # AI classifier uses user's LLM router (if provided)
        if use_ai:
            try:
                self._ai_classifier = get_ai_classifier(llm_router=llm_router)
            except Exception as e:
                logger.debug(f"AI classifier unavailable: {e}")

        # Initialize smart classifier for learning (local embeddings)
        try:
            self._smart_classifier = get_smart_classifier(db_client=db_client)
        except Exception as e:
            logger.debug(f"Smart classifier unavailable: {e}")

    def classify(self, user_query: str, system_state=None) -> PriorityResult:
        """Classify the user query (legacy, returns PriorityResult only)."""
        self._last_query = user_query  # Track for feedback
        result = self.classifier.classify(user_query, system_state=system_state)
        _ = get_behavior(result.priority)
        return result

    async def classify_full_async(self, user_query: str, system_state=None) -> TriageContext:
        """
        Full classification using local embeddings first, then LLM fallback.

        Priority:
        1. SmartTriageClassifier (local embeddings - fast, no API)
        2. AITriageClassifier (LLM API - only if embeddings unavailable)
        3. Keyword-based fallback
        """
        self._last_query = user_query  # Track for feedback

        # 1. Try SmartTriageClassifier first (local embeddings, no API call)
        if self._smart_classifier:
            try:
                intent, priority_result = self._smart_classifier.classify(user_query)

                return TriageContext(
                    priority_result=priority_result,
                    intent=intent,
                    intent_confidence=priority_result.confidence,
                    intent_signals=[f"smart:{intent.value}"],
                    allowed_tools=intent.allowed_tools,
                    query=user_query,
                )
            except Exception as e:
                logger.debug(f"Smart classifier failed: {e}")

        # 2. Fallback to AI classifier (LLM API) only if smart classifier unavailable
        if self._ai_classifier:
            try:
                ai_result = await self._ai_classifier.classify(user_query)

                priority_result = PriorityResult(
                    priority=ai_result.priority,
                    confidence=0.9 if not ai_result.from_cache else 0.95,
                    signals=[f"ai:{ai_result.intent.value}"],
                    reasoning=ai_result.reasoning,
                    escalation_required=ai_result.priority.value == 0,
                )

                return TriageContext(
                    priority_result=priority_result,
                    intent=ai_result.intent,
                    intent_confidence=0.9,
                    intent_signals=[f"ai:{ai_result.reasoning[:50]}"],
                    allowed_tools=ai_result.intent.allowed_tools,
                    query=user_query,
                )

            except Exception as e:
                logger.debug(f"AI classification failed, using fallback: {e}")

        # 3. Final fallback to keyword-based
        return self.classify_full(user_query, system_state)

    def classify_full(self, user_query: str, system_state=None) -> TriageContext:
        """
        Full classification including intent detection (sync, keyword-based).

        For AI-powered classification, use classify_full_async().

        Returns:
            TriageContext with priority, intent, and allowed tools
        """
        self._last_query = user_query  # Track for feedback

        # Try sync AI classification (cache only, no LLM call)
        if self._ai_classifier:
            cached = self._ai_classifier._get_from_cache(user_query)
            if cached:
                priority_result = PriorityResult(
                    priority=cached.priority,
                    confidence=0.95,
                    signals=[f"ai_cached:{cached.intent.value}"],
                    reasoning=cached.reasoning,
                    escalation_required=cached.priority.value == 0,
                )
                return TriageContext(
                    priority_result=priority_result,
                    intent=cached.intent,
                    intent_confidence=0.95,
                    intent_signals=["cached"],
                    allowed_tools=cached.intent.allowed_tools,
                    query=user_query,
                )

        # Keyword-based classification
        priority_result = self.classifier.classify(user_query, system_state=system_state)

        # Intent detection
        intent, intent_conf, intent_signals = self.signal_detector.detect_intent(user_query)

        # Determine allowed tools based on intent
        allowed_tools = intent.allowed_tools

        return TriageContext(
            priority_result=priority_result,
            intent=intent,
            intent_confidence=intent_conf,
            intent_signals=intent_signals,
            allowed_tools=allowed_tools,
            query=user_query,
        )

    def display_triage(self, result: PriorityResult):
        """Display triage information to the console (legacy)."""
        self._display_priority(result)

    def display_full_triage(self, context: TriageContext):
        """Display full triage with intent information."""
        self._display_priority(context.priority_result, context.intent)

    def _display_priority(self, result: PriorityResult, intent: Optional[Intent] = None):
        """Internal method to display priority info."""
        should_display = True
        if self.verbosity:
            should_display = self.verbosity.should_output(VerbosityLevel.NORMAL)

        if not should_display:
            return

        priority = result.priority
        color = priority.color
        label = priority.label

        priority_text = f"[bold {color}]{priority.name}[/bold {color}] - {label}"

        if result.environment_detected:
            priority_text += f" | env: {result.environment_detected}"
        if result.service_detected:
            priority_text += f" | service: {result.service_detected}"
        if result.host_detected:
            priority_text += f" | host: {result.host_detected}"

        # Add intent if available
        if intent:
            intent_color = {
                Intent.QUERY: "cyan",
                Intent.ACTION: "yellow",
                Intent.ANALYSIS: "magenta",
            }.get(intent, "white")
            priority_text += f" | [bold {intent_color}]intent: {intent.value}[/bold {intent_color}]"

        self.console.print(Panel(
            f"{priority_text}\n[dim]{result.reasoning}[/dim]",
            title="🎯 Triage",
            border_style=color,
            padding=(0, 1),
        ))

        # Show behavior mode
        behavior_desc = describe_behavior(priority)
        self.console.print(f"[dim]Mode: {behavior_desc}[/dim]\n")

    def provide_feedback(
        self,
        query: Optional[str],
        correct_intent: Intent,
        correct_priority: Priority,
    ) -> bool:
        """
        Provide feedback to improve future classifications.

        Args:
            query: Query to correct. If None, uses last classified query.
            correct_intent: The correct intent
            correct_priority: The correct priority

        Returns:
            True if feedback was stored successfully
        """
        target_query = query or self._last_query
        if not target_query:
            logger.warning("No query to provide feedback for")
            return False

        if not self._smart_classifier:
            logger.warning("Smart classifier not available for feedback")
            return False

        success = self._smart_classifier.provide_feedback(
            target_query, correct_intent, correct_priority
        )

        if success:
            logger.info(f"Feedback stored: {correct_intent.value}/{correct_priority.name}")

        return success

    def get_feedback_options(self) -> dict:
        """Get available feedback options for display."""
        return {
            "intents": {i.value: i.name for i in Intent},
            "priorities": {p.name: p.label for p in Priority},
        }

    def get_learning_stats(self) -> dict:
        """Get statistics about learned patterns."""
        if not self._smart_classifier:
            return {"available": False, "reason": "Smart classifier not initialized"}

        return self._smart_classifier.get_stats()

    def confirm_last_classification(self) -> bool:
        """
        Confirm last classification was correct (implicit positive feedback).

        Call this after a successful request to gradually build confidence
        in the classification. After ~3 successful uses without correction,
        the pattern becomes trusted (confidence >= 0.7).

        Returns:
            True if confirmation was stored, False otherwise
        """
        if not self._last_query:
            return False

        if not self._smart_classifier:
            return False

        return self._smart_classifier.confirm_classification(self._last_query)
