"""
Behavior Profiles for priority-based execution.

Different priorities trigger different agent behaviors:
- P0: Fast response, minimal analysis, auto-confirm reads
- P1: Quick analysis, auto-confirm reads
- P2: Thorough analysis, confirm writes
- P3: Detailed analysis, confirm everything
"""

from dataclasses import dataclass
from typing import Dict

from .priority import Priority


@dataclass(frozen=True)
class BehaviorProfile:
    """Execution behavior based on priority."""

    # Analysis depth
    max_analysis_time_seconds: int
    use_chain_of_thought: bool
    show_thinking: bool

    # Execution style
    parallel_execution: bool  # Run commands in parallel
    auto_confirm_reads: bool  # Auto-confirm read-only commands
    auto_confirm_writes: bool  # Auto-confirm write commands (dangerous!)
    max_commands_before_pause: int

    # Confirmation behavior
    confirmation_mode: str  # "none", "critical_only", "writes_only", "all"

    # Response style
    response_format: str  # "terse", "standard", "detailed"
    include_next_steps: bool
    include_explanations: bool

    def should_confirm(self, is_write: bool, is_critical: bool) -> bool:
        """Determine if confirmation is needed for a command."""
        if self.confirmation_mode == "none":
            return False
        elif self.confirmation_mode == "critical_only":
            return is_critical
        elif self.confirmation_mode == "writes_only":
            return is_write
        elif self.confirmation_mode == "all":
            return True
        return True  # Default to safe

    def should_auto_confirm(self, is_write: bool) -> bool:
        """Determine if auto-confirmation is appropriate."""
        if is_write:
            return self.auto_confirm_writes
        return self.auto_confirm_reads


# Pre-defined behavior profiles for each priority level
BEHAVIOR_PROFILES: Dict[Priority, BehaviorProfile] = {
    Priority.P0: BehaviorProfile(
        # P0: CRITICAL - Act fast, minimal friction
        max_analysis_time_seconds=5,
        use_chain_of_thought=False,  # No time for deep thinking
        show_thinking=False,
        parallel_execution=True,  # Gather info fast
        auto_confirm_reads=True,  # Always auto-confirm reads
        auto_confirm_writes=False,  # Still require confirmation for writes
        max_commands_before_pause=10,  # More freedom to investigate
        confirmation_mode="critical_only",
        response_format="terse",  # Short, actionable
        include_next_steps=True,
        include_explanations=False,
    ),

    Priority.P1: BehaviorProfile(
        # P1: URGENT - Quick but thoughtful
        max_analysis_time_seconds=30,
        use_chain_of_thought=True,  # Can think, but quickly
        show_thinking=False,  # Don't clutter output
        parallel_execution=True,
        auto_confirm_reads=True,
        auto_confirm_writes=False,
        max_commands_before_pause=8,
        confirmation_mode="critical_only",
        response_format="standard",
        include_next_steps=True,
        include_explanations=False,
    ),

    Priority.P2: BehaviorProfile(
        # P2: IMPORTANT - Thorough analysis
        max_analysis_time_seconds=120,
        use_chain_of_thought=True,
        show_thinking=True,  # Show reasoning
        parallel_execution=False,  # Sequential is fine
        auto_confirm_reads=True,
        auto_confirm_writes=False,
        max_commands_before_pause=5,
        confirmation_mode="writes_only",
        response_format="detailed",
        include_next_steps=True,
        include_explanations=True,
    ),

    Priority.P3: BehaviorProfile(
        # P3: NORMAL - Full analysis, careful execution
        max_analysis_time_seconds=300,
        use_chain_of_thought=True,
        show_thinking=True,
        parallel_execution=False,
        auto_confirm_reads=False,  # Ask for everything (maintenance mode)
        auto_confirm_writes=False,
        max_commands_before_pause=3,
        confirmation_mode="all",
        response_format="detailed",
        include_next_steps=False,  # Let user decide
        include_explanations=True,
    ),
}


def get_behavior(priority: Priority) -> BehaviorProfile:
    """Get the behavior profile for a given priority."""
    return BEHAVIOR_PROFILES.get(priority, BEHAVIOR_PROFILES[Priority.P3])


def describe_behavior(priority: Priority) -> str:
    """Get a human-readable description of the behavior for a priority."""
    behavior = get_behavior(priority)

    descriptions = {
        Priority.P0: (
            "FAST MODE: Auto-confirming read commands, "
            f"max {behavior.max_commands_before_pause} commands before pause, "
            "terse responses"
        ),
        Priority.P1: (
            "QUICK MODE: Auto-confirming reads, "
            f"max {behavior.max_commands_before_pause} commands before pause, "
            "standard responses"
        ),
        Priority.P2: (
            "THOROUGH MODE: Confirming write commands, "
            f"max {behavior.max_commands_before_pause} commands before pause, "
            "detailed responses with explanations"
        ),
        Priority.P3: (
            "CAREFUL MODE: Confirming all commands, "
            f"max {behavior.max_commands_before_pause} commands before pause, "
            "detailed responses with explanations"
        ),
    }

    return descriptions.get(priority, "Unknown mode")
