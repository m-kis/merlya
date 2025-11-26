from dataclasses import dataclass
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel

from athena_ai.triage import (
    Intent,
    PriorityClassifier,
    PriorityResult,
    SignalDetector,
    describe_behavior,
    get_behavior,
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


class IntentParser:
    """Handles intent classification and priority display."""

    def __init__(self, console: Console, verbosity=None, use_ai: bool = True):
        self.console = console
        self.verbosity = verbosity
        self.classifier = PriorityClassifier()
        self.signal_detector = SignalDetector()
        self._use_ai = use_ai
        self._ai_classifier: Optional[AITriageClassifier] = None
        if use_ai:
            try:
                self._ai_classifier = get_ai_classifier()
            except Exception as e:
                logger.debug(f"AI classifier unavailable: {e}")

    def classify(self, user_query: str, system_state=None) -> PriorityResult:
        """Classify the user query (legacy, returns PriorityResult only)."""
        result = self.classifier.classify(user_query, system_state=system_state)
        _ = get_behavior(result.priority)
        return result

    async def classify_full_async(self, user_query: str, system_state=None) -> TriageContext:
        """
        Full classification using AI (async).

        Uses LLM for intelligent intent/priority detection with keyword fallback.
        """
        if self._ai_classifier:
            try:
                ai_result = await self._ai_classifier.classify(user_query)

                # Build PriorityResult from AI classification
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
                )

            except Exception as e:
                logger.debug(f"AI classification failed, using fallback: {e}")

        # Fallback to keyword-based
        return self.classify_full(user_query, system_state)

    def classify_full(self, user_query: str, system_state=None) -> TriageContext:
        """
        Full classification including intent detection (sync, keyword-based).

        For AI-powered classification, use classify_full_async().

        Returns:
            TriageContext with priority, intent, and allowed tools
        """
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
        )

    def display_triage(self, result: PriorityResult):
        """Display triage information to the console (legacy)."""
        self._display_priority(result)

    def display_full_triage(self, context: TriageContext):
        """Display full triage with intent information."""
        self._display_priority(context.priority_result, context.intent)

    def _display_priority(self, result: PriorityResult, intent: Intent = None):
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
