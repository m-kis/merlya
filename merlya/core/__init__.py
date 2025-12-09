"""
Merlya Core - Shared context and types.
"""

from merlya.core.bootstrap import BootstrapResult, bootstrap
from merlya.core.context import SharedContext, get_context
from merlya.core.logging import configure_logging, get_logger
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
    "HealthCheck",
    "HostStatus",
    "Priority",
    "RiskLevel",
    "SharedContext",
    "bootstrap",
    "configure_logging",
    "get_context",
    "get_logger",
]
