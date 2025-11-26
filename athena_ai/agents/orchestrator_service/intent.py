from rich.console import Console
from rich.panel import Panel

from athena_ai.triage import (
    PriorityClassifier,
    PriorityResult,
    describe_behavior,
    get_behavior,
)
from athena_ai.utils.verbosity import VerbosityLevel


class IntentParser:
    """Handles intent classification and priority display."""

    def __init__(self, console: Console, verbosity=None):
        self.console = console
        self.verbosity = verbosity
        self.classifier = PriorityClassifier()

    def classify(self, user_query: str, system_state=None) -> PriorityResult:
        """Classify the user query."""
        result = self.classifier.classify(user_query, system_state=system_state)

        # Get behavior profile (for future adaptive behavior)
        _ = get_behavior(result.priority)

        return result

    def display_triage(self, result: PriorityResult):
        """Display triage information to the console."""
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

        self.console.print(Panel(
            f"{priority_text}\n[dim]{result.reasoning}[/dim]",
            title="🎯 Triage",
            border_style=color,
            padding=(0, 1),
        ))

        # Show behavior mode
        behavior_desc = describe_behavior(priority)
        self.console.print(f"[dim]Mode: {behavior_desc}[/dim]\n")
