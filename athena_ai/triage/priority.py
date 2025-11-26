"""
Priority and Intent definitions for incident triage.

P0 = CRITICAL: Production down, data loss, security breach
P1 = URGENT: Service degraded, security vulnerability, imminent failure
P2 = IMPORTANT: Performance issues, non-critical failures
P3 = NORMAL: Maintenance, improvements, monitoring checks

Intent types:
- QUERY: Information request (list hosts, show status) - read-only
- ACTION: Execute commands, make changes
- ANALYSIS: Deep investigation, diagnostics
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import List, Optional


class Intent(Enum):
    """
    Request intent classification.

    Determines what type of operation the user wants:
    - QUERY: Just asking for information (read-only)
    - ACTION: Execute commands or make changes
    - ANALYSIS: Deep investigation requiring multiple steps
    """
    QUERY = "query"        # "quels sont mes serveurs", "list hosts", "show me"
    ACTION = "action"      # "restart nginx", "check disk", "execute"
    ANALYSIS = "analysis"  # "analyze performance", "diagnose issue"

    @property
    def allowed_tools(self) -> Optional[List[str]]:
        """Tools allowed for this intent type. None means all tools allowed."""
        if self == Intent.QUERY:
            return ["list_hosts", "get_infrastructure_context", "recall_skill"]
        # ACTION and ANALYSIS: all tools allowed
        return None


class Priority(IntEnum):
    """
    Incident priority levels.
    Lower number = higher priority (P0 is most critical).
    """
    P0 = 0  # CRITICAL
    P1 = 1  # URGENT
    P2 = 2  # IMPORTANT
    P3 = 3  # NORMAL

    @property
    def label(self) -> str:
        """Human-readable label."""
        labels = {
            Priority.P0: "CRITICAL",
            Priority.P1: "URGENT",
            Priority.P2: "IMPORTANT",
            Priority.P3: "NORMAL",
        }
        return labels[self]

    @property
    def color(self) -> str:
        """Rich color for display."""
        colors = {
            Priority.P0: "bold red",
            Priority.P1: "bold yellow",
            Priority.P2: "cyan",
            Priority.P3: "dim white",
        }
        return colors[self]

    @property
    def response_time_seconds(self) -> int:
        """Suggested response time in seconds."""
        times = {
            Priority.P0: 60,      # 1 minute
            Priority.P1: 300,     # 5 minutes
            Priority.P2: 3600,    # 1 hour
            Priority.P3: 86400,   # 1 day
        }
        return times[self]


@dataclass
class TriageResult:
    """Result of triage classification (priority + intent)."""

    priority: Priority
    intent: Intent
    confidence: float  # 0.0 to 1.0
    signals: List[str] = field(default_factory=list)
    reasoning: str = ""
    escalation_required: bool = False
    detected_at: datetime = field(default_factory=datetime.now)

    # Context that influenced the classification
    environment_detected: Optional[str] = None  # prod, staging, dev
    service_detected: Optional[str] = None
    host_detected: Optional[str] = None


# Backward compatibility alias
@dataclass
class PriorityResult:
    """Result of priority classification (legacy, use TriageResult)."""

    priority: Priority
    confidence: float  # 0.0 to 1.0
    signals: List[str] = field(default_factory=list)
    reasoning: str = ""
    escalation_required: bool = False
    detected_at: datetime = field(default_factory=datetime.now)

    # Context that influenced the classification
    environment_detected: Optional[str] = None  # prod, staging, dev
    service_detected: Optional[str] = None
    host_detected: Optional[str] = None

    @property
    def suggested_response_time(self) -> int:
        """Response time in seconds based on priority."""
        return self.priority.response_time_seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "priority": self.priority.name,
            "priority_label": self.priority.label,
            "confidence": self.confidence,
            "signals": self.signals,
            "reasoning": self.reasoning,
            "escalation_required": self.escalation_required,
            "detected_at": self.detected_at.isoformat(),
            "environment": self.environment_detected,
            "service": self.service_detected,
            "host": self.host_detected,
            "response_time_seconds": self.suggested_response_time,
        }

    def __str__(self) -> str:
        signals_str = ", ".join(self.signals[:3])
        if len(self.signals) > 3:
            signals_str += f" (+{len(self.signals) - 3} more)"
        return (
            f"[{self.priority.name}] {self.priority.label} "
            f"(confidence: {self.confidence:.0%}) - {signals_str}"
        )
