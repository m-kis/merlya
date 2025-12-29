"""
Merlya Core - Shared context and types.

v0.8.0: Introduces focused sub-contexts and Result[T] pattern.
"""

from merlya.core.bootstrap import BootstrapResult, bootstrap
from merlya.core.context import SharedContext, get_context
from merlya.core.contexts import (
    ConfigContext,
    DataContext,
    ExecutionContext,
    SessionState,
    UIContext,
)
from merlya.core.logging import configure_logging, get_logger
from merlya.core.result import Result
from merlya.core.types import (
    AgentMode,
    CheckStatus,
    CommandResult,
    HealthCheck,
    HostStatus,
    Priority,
    RiskLevel,
)

__all__ = [
    "AgentMode",
    "BootstrapResult",
    "CheckStatus",
    "CommandResult",
    "ConfigContext",
    "DataContext",
    "ExecutionContext",
    "HealthCheck",
    "HostStatus",
    "Priority",
    "Result",
    "RiskLevel",
    "SessionState",
    "SharedContext",
    "UIContext",
    "bootstrap",
    "configure_logging",
    "get_context",
    "get_logger",
]
