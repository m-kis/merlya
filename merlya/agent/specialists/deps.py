"""
Merlya Agent Specialists - Dependencies.

Shared dependencies dataclass for all specialist agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from merlya.agent.confirmation import ConfirmationState
from merlya.agent.tracker import ToolCallTracker

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class SpecialistDeps:
    """Dependencies for specialist agents.

    Attributes:
        context: Shared context with config, hosts, secrets, etc.
        tracker: Tool call tracker for loop detection.
        confirmation_state: State for command confirmation.
        target: Target host or "local".
    """

    context: SharedContext
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    confirmation_state: ConfirmationState = field(default_factory=ConfirmationState)
    target: str = "local"
