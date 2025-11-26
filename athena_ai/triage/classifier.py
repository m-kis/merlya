"""
Priority Classifier for incident triage.

Combines signal detection with context analysis to determine
the appropriate priority level for a request.
"""

from typing import Optional, Dict, Any
from datetime import datetime

from .priority import Priority, PriorityResult
from .signals import SignalDetector


class PriorityClassifier:
    """
    Main classifier that determines incident priority.

    Uses multi-layer detection:
    1. Keyword matching (fastest)
    2. Environment/context analysis
    3. Impact amplifiers
    4. Optional: System state (if available)
    """

    def __init__(self):
        self.signal_detector = SignalDetector()
        self._classification_count = 0

    def classify(
        self,
        query: str,
        system_state: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PriorityResult:
        """
        Classify priority for a user query.

        P0/P1 detection is FAST (< 10ms) - no LLM involved.
        Uses keyword and pattern matching only.

        Args:
            query: The user's query text
            system_state: Optional dict with current system metrics
            context: Optional dict with additional context (host info, etc.)

        Returns:
            PriorityResult with classification details
        """
        self._classification_count += 1

        # Run all signal detections
        signals = self.signal_detector.detect_all(query)

        # Start with keyword-based priority
        base_priority = signals["keyword_priority"]
        base_signals = signals["keyword_signals"]
        confidence = signals["keyword_confidence"]

        all_signals = list(base_signals)

        # Apply environment constraints
        env = signals["environment"]
        env_min = signals["env_min_priority"]
        if env:
            all_signals.append(f"env:{env}")
            # In production, minimum priority is P1
            if env_min is not None and base_priority > env_min:
                if env == "prod":
                    base_priority = min(base_priority, env_min)
                    all_signals.append("prod_escalation")
                    confidence = min(confidence + 0.1, 0.95)

        # Apply impact multiplier
        impact_mult = signals["impact_multiplier"]
        if impact_mult > 1.0:
            all_signals.append(f"impact:{impact_mult:.1f}x")
            # High impact can escalate priority by 1 level
            if impact_mult >= 1.5 and base_priority > Priority.P0:
                base_priority = Priority(base_priority - 1)
                confidence = min(confidence + 0.1, 0.95)

        # Check system state if provided
        if system_state:
            state_priority = self._check_system_state(system_state)
            if state_priority is not None and state_priority < base_priority:
                base_priority = state_priority
                all_signals.append(f"system_state:{state_priority.name}")
                confidence = max(confidence, 0.85)

        # Determine if escalation is required
        escalation_required = base_priority == Priority.P0

        # Build reasoning
        reasoning = self._build_reasoning(
            base_priority, all_signals, env, impact_mult
        )

        return PriorityResult(
            priority=base_priority,
            confidence=confidence,
            signals=all_signals,
            reasoning=reasoning,
            escalation_required=escalation_required,
            detected_at=datetime.now(),
            environment_detected=env,
            service_detected=signals["service"],
            host_detected=signals["host"],
        )

    def _check_system_state(self, state: Dict[str, Any]) -> Optional[Priority]:
        """
        Check system state for priority indicators.

        Args:
            state: Dict with keys like "host_accessible", "disk_usage", etc.

        Returns:
            Priority if state indicates urgency, None otherwise
        """
        # Host unreachable is always P0
        if state.get("host_accessible") is False:
            return Priority.P0

        # Critical service down
        if state.get("critical_service_down"):
            return Priority.P0

        # Disk > 95%
        disk_usage = state.get("disk_usage_percent")
        if disk_usage and disk_usage > 95:
            return Priority.P1
        elif disk_usage and disk_usage > 90:
            return Priority.P2

        # Memory > 95%
        memory_usage = state.get("memory_usage_percent")
        if memory_usage and memory_usage > 95:
            return Priority.P1
        elif memory_usage and memory_usage > 90:
            return Priority.P2

        # High load
        load_per_cpu = state.get("load_per_cpu")
        if load_per_cpu and load_per_cpu > 2.0:
            return Priority.P1
        elif load_per_cpu and load_per_cpu > 1.0:
            return Priority.P2

        return None

    def _build_reasoning(
        self,
        priority: Priority,
        signals: list,
        environment: Optional[str],
        impact_mult: float,
    ) -> str:
        """Build human-readable reasoning for the classification."""
        parts = []

        if priority == Priority.P0:
            parts.append("Critical indicators detected")
        elif priority == Priority.P1:
            parts.append("Urgent indicators detected")
        elif priority == Priority.P2:
            parts.append("Performance/non-critical indicators")
        else:
            parts.append("Standard priority request")

        if environment:
            if environment == "prod":
                parts.append("production environment")
            elif environment in ("staging", "preprod"):
                parts.append("staging environment")

        if impact_mult > 1.0:
            parts.append("high impact detected")

        keyword_signals = [s for s in signals if ":" in s and s.split(":")[0] in ("P0", "P1", "P2")]
        if keyword_signals:
            keywords = [s.split(":")[1] for s in keyword_signals[:2]]
            parts.append(f"keywords: {', '.join(keywords)}")

        return "; ".join(parts)

    @property
    def classification_count(self) -> int:
        """Number of classifications performed."""
        return self._classification_count


# Singleton instance for easy access
_default_classifier: Optional[PriorityClassifier] = None


def get_classifier() -> PriorityClassifier:
    """Get the default classifier instance."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = PriorityClassifier()
    return _default_classifier


def classify_priority(query: str, **kwargs) -> PriorityResult:
    """
    Convenience function to classify priority.

    Usage:
        result = classify_priority("MongoDB is down on prod-db-01")
        print(result.priority)  # Priority.P0
    """
    return get_classifier().classify(query, **kwargs)
