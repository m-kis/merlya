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
from merlya.core.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    get_metrics_summary,
    get_registry,
    reset_metrics,
    timing,
    track_command,
    track_llm_call,
    track_pipeline_execution,
    track_ssh_duration,
)
from merlya.core.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    circuit_breaker,
    get_resilience_metrics,
    reset_circuit_breaker,
    reset_resilience_metrics,
    retry,
)
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
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitState",
    "CommandResult",
    "ConfigContext",
    "Counter",
    "DataContext",
    "ExecutionContext",
    "Gauge",
    "HealthCheck",
    "Histogram",
    "HostStatus",
    "MetricsRegistry",
    "Priority",
    "Result",
    "RiskLevel",
    "SessionState",
    "SharedContext",
    "UIContext",
    "bootstrap",
    "circuit_breaker",
    "configure_logging",
    "get_context",
    "get_logger",
    "get_metrics_summary",
    "get_registry",
    "get_resilience_metrics",
    "reset_circuit_breaker",
    "reset_metrics",
    "reset_resilience_metrics",
    "retry",
    "timing",
    "track_command",
    "track_llm_call",
    "track_pipeline_execution",
    "track_ssh_duration",
]
