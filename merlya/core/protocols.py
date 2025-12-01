"""
Core Protocols - Interfaces for all components.

Follows LSP and DIP principles: depend on abstractions, not concretions.
"""
from typing import Any, Generic, Protocol, TypedDict, TypeVar, runtime_checkable

# Generic type for Store protocol
T = TypeVar("T")

# =============================================================================
# Result Types (TypedDict for type safety)
# =============================================================================

class AgentResult(TypedDict, total=False):
    """Standard result from agent execution."""
    success: bool
    data: Any
    error: str | None
    execution_time_ms: int


class ToolResult(TypedDict, total=False):
    """Standard result from tool execution."""
    success: bool
    output: str
    error: str | None


class OrchestratorResult(TypedDict, total=False):
    """Standard result from orchestrator."""
    response: str
    priority: str | None
    execution_time_ms: int


# =============================================================================
# Agent Protocol
# =============================================================================

@runtime_checkable
class Agent(Protocol):
    """
    Protocol for all agents.

    All agents must implement this interface to be used polymorphically.
    """
    name: str

    def run(self, task: str, **kwargs) -> AgentResult:
        """Execute agent task."""
        ...


# =============================================================================
# Tool Protocol
# =============================================================================

@runtime_checkable
class Tool(Protocol):
    """
    Protocol for all tools.

    Tools are functions wrapped with metadata for discovery and registration.
    """
    name: str
    description: str

    def execute(self, **params) -> ToolResult:
        """Execute the tool with given parameters."""
        ...


# =============================================================================
# Store Protocol (Generic Repository Pattern)
# =============================================================================

@runtime_checkable
class Store(Protocol, Generic[T]):
    """
    Generic store protocol for persistence.

    Implements Repository pattern with CRUD operations.
    """

    def save(self, entity: T) -> None:
        """Save entity to store."""
        ...

    def load(self, entity_id: str) -> T | None:
        """Load entity by ID."""
        ...

    def delete(self, entity_id: str) -> None:
        """Delete entity by ID."""
        ...

    def list_all(self) -> list[T]:
        """List all entities."""
        ...


# =============================================================================
# Orchestrator Protocol
# =============================================================================

@runtime_checkable
class Orchestrator(Protocol):
    """
    Protocol for orchestrators.

    Orchestrators process user requests and coordinate agents.
    """

    async def process_request(
        self,
        user_query: str,
        auto_confirm: bool = False,
        dry_run: bool = False,
        **kwargs
    ) -> str:
        """Process user request."""
        ...

    def reset_session(self) -> None:
        """Reset conversation session."""
        ...


# =============================================================================
# Planning Protocol
# =============================================================================

class Plan(TypedDict):
    """Execution plan structure."""
    title: str
    steps: list[dict[str, Any]]
    estimated_risk: str
    requires_confirmation: bool


@runtime_checkable
class PlanningStrategy(Protocol):
    """
    Protocol for planning strategies.

    Allows different planning approaches (pattern-based, LLM-based, etc.)
    """

    def create_plan(self, request: str, context: dict[str, Any]) -> Plan:
        """Create execution plan from request."""
        ...


# =============================================================================
# LLM Router Protocol
# =============================================================================

@runtime_checkable
class LLMRouter(Protocol):
    """Protocol for LLM routing."""

    async def complete(self, prompt: str, **kwargs) -> str:
        """Get completion from LLM."""
        ...

    def get_model_info(self) -> dict[str, Any]:
        """Get current model information."""
        ...
