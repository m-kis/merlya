"""
Core Module for Merlya.

Provides shared types, enums, protocols and base classes used across the application.
Following DRY principle - centralized definitions to avoid duplicates.
"""
from .exceptions import (
    AgentError,
    AgentNotFoundError,
    CommandFailedError,
    CommandTimeoutError,
    ConfigurationError,
    ConnectionError,
    ExecutionError,
    HostNotFoundError,
    InvalidConfigError,
    MerlyaError,
    MissingAPIKeyError,
    OrchestratorError,
    PermissionDeniedError,
    PlanError,
    PlanExecutionError,
    PlanValidationError,
    RiskLevelExceededError,
    SecurityError,
    SSHConnectionError,
    ValidationError,
)
from .hooks import HookContext, HookEvent, HookManager, get_hook_manager
from .protocols import (
    Agent,
    AgentResult,
    LLMRouter,
    Orchestrator,
    Plan,
    PlanningStrategy,
    Store,
    Tool,
    ToolResult,
)
from .registry import (
    AgentRegistry,
    get_agent,
    get_registry,
    register_agent,
    register_builtin_agents,
)
from .types import RequestComplexity, StepStatus

__all__ = [
    # Types
    "StepStatus",
    "RequestComplexity",
    # Hooks
    "HookEvent",
    "HookContext",
    "HookManager",
    "get_hook_manager",
    # Registry (OCP)
    "AgentRegistry",
    "get_registry",
    "register_agent",
    "get_agent",
    "register_builtin_agents",
    # Protocols
    "Agent",
    "AgentResult",
    "Tool",
    "ToolResult",
    "Store",
    "Orchestrator",
    "Plan",
    "PlanningStrategy",
    "LLMRouter",
    # Exceptions
    "MerlyaError",
    "ValidationError",
    "HostNotFoundError",
    "InvalidConfigError",
    "ExecutionError",
    "SSHConnectionError",
    "CommandTimeoutError",
    "CommandFailedError",
    "ConnectionError",
    "PlanError",
    "PlanValidationError",
    "PlanExecutionError",
    "AgentError",
    "AgentNotFoundError",
    "OrchestratorError",
    "SecurityError",
    "PermissionDeniedError",
    "RiskLevelExceededError",
    "ConfigurationError",
    "MissingAPIKeyError",
]
