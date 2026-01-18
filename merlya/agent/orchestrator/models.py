"""
Orchestrator models.

Contains dataclasses and Pydantic models used by the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_ai.usage import Usage

from merlya.agent.confirmation import ConfirmationState
from merlya.agent.tracker import ToolCallTracker

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class SecurityError(Exception):
    """Raised when potentially unsafe input is detected."""

    pass


@dataclass
class OrchestratorDeps:
    """Dependencies for the Orchestrator."""

    context: SharedContext
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    confirmation_state: ConfirmationState = field(default_factory=ConfirmationState)
    usage: Usage = field(default_factory=Usage)


class DelegationResult(BaseModel):
    """Result from a specialist agent."""

    success: bool
    output: str
    specialist: str
    tool_calls: int = 0
    complete: bool = True  # Whether the task was fully completed


class OrchestratorResponse(BaseModel):
    """Response from the Orchestrator."""

    message: str = Field(description="Final response to user")
    delegations: list[str] = Field(default_factory=list, description="Specialists used")
    actions_summary: list[str] = Field(default_factory=list, description="Actions taken")
