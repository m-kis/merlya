"""
Merlya Core - Resilience patterns.

Provides circuit breaker and retry decorators for resilient operations.
Targets: SSH, LLM, Pipeline operations.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from threading import Lock
from typing import Any, TypeVar

from loguru import logger

from merlya.core.metrics import get_registry

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit tripped, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    failure_threshold: int = 5  # Failures before opening circuit
    recovery_timeout: int = 60  # Seconds before attempting recovery
    success_threshold: int = 2  # Successes needed in half-open to close


class CircuitBreaker:
    """
    Circuit breaker implementation.

    Tracks failures and opens circuit after threshold.
    Auto-recovery after timeout period.

    Pattern from Architecture Decision:
    - failure_threshold=5: Open circuit after 5 consecutive failures
    - recovery_timeout=60: Wait 60s before testing recovery
    - success_threshold=2: Need 2 successes to fully close circuit
    """

    def __init__(self, config: CircuitBreakerConfig) -> None:
        """Initialize circuit breaker."""
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """
        Execute function through circuit breaker.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: Original exception from function
        """
        async with self._lock:
            # Check if circuit should transition from OPEN to HALF_OPEN
            if self.state == CircuitState.OPEN:
                if self.last_failure_time and (
                    time.time() - self.last_failure_time >= self.config.recovery_timeout
                ):
                    logger.info("🔄 Circuit breaker: OPEN → HALF_OPEN (testing recovery)")
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    remaining = self.config.recovery_timeout - (time.time() - self.last_failure_time)
                    logger.warning(
                        f"🔴 Circuit breaker OPEN: {self.failure_count} failures, "
                        f"recovery in {remaining:.1f}s"
                    )
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is OPEN (failed {self.failure_count} times)"
                    )

        # Execute function
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise e

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                logger.info(
                    f"🟢 Circuit breaker success in HALF_OPEN ({self.success_count}/{self.config.success_threshold})"
                )
                if self.success_count >= self.config.success_threshold:
                    logger.info("✅ Circuit breaker: HALF_OPEN → CLOSED (service recovered)")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                if self.failure_count > 0:
                    logger.debug(f"✅ Circuit breaker: Reset failure count (was {self.failure_count})")
                self.failure_count = 0

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                logger.warning("⚠️ Circuit breaker: HALF_OPEN → OPEN (recovery failed)")
                self.state = CircuitState.OPEN
                self.success_count = 0
            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    logger.error(
                        f"🔴 Circuit breaker: CLOSED → OPEN (threshold {self.config.failure_threshold} reached)"
                    )
                    self.state = CircuitState.OPEN

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        logger.debug("🔄 Circuit breaker reset to CLOSED")


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


# Global circuit breakers registry (keyed by function name)
_circuit_breakers: dict[str, CircuitBreaker] = {}
_circuit_breakers_lock = Lock()


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    success_threshold: int = 2,
    key: str | None = None,
) -> Callable:
    """
    Circuit breaker decorator.

    Args:
        failure_threshold: Failures before opening circuit (default: 5)
        recovery_timeout: Seconds before attempting recovery (default: 60)
        success_threshold: Successes needed to close circuit (default: 2)
        key: Optional key for circuit breaker (default: function name)

    Returns:
        Decorated function

    Example:
        @circuit_breaker(failure_threshold=5, recovery_timeout=60)
        async def ssh_execute(...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        # Use custom key or function name
        breaker_key = key or f"{func.__module__}.{func.__name__}"

        # Create circuit breaker for this function (thread-safe)
        with _circuit_breakers_lock:
            if breaker_key not in _circuit_breakers:
                config = CircuitBreakerConfig(
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    success_threshold=success_threshold,
                )
                _circuit_breakers[breaker_key] = CircuitBreaker(config)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            breaker = _circuit_breakers[breaker_key]
            return await breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    exponential_base: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum retry attempts (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay in seconds (default: 10.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        exceptions: Exception types to retry (default: all exceptions)

    Returns:
        Decorated function

    Example:
        @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
        async def ssh_execute(...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None
            metrics_registry = get_registry()

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"❌ Retry exhausted after {max_attempts} attempts: {func.__name__}"
                        )
                        raise e

                    # Track retry attempt in metrics (only for actual retries, not first attempt)
                    metrics_registry.counter("merlya_retry_attempts_total").inc(
                        function=func.__name__, attempt=str(attempt)
                    )

                    # Calculate exponential backoff delay
                    delay = min(initial_delay * (exponential_base ** (attempt - 1)), max_delay)
                    error_msg = str(e)[:80] + "..." if len(str(e)) > 80 else str(e)
                    logger.warning(
                        f"🔄 Retry {attempt}/{max_attempts} for {func.__name__} after {delay:.1f}s: {error_msg}"
                    )
                    await asyncio.sleep(delay)

            # Should never reach here, but satisfy type checker
            if last_exception:
                raise last_exception
            raise RuntimeError("Retry logic error")

        return wrapper

    return decorator


# Metrics tracking for resilience patterns
@dataclass
class ResilienceMetrics:
    """Resilience metrics for monitoring."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    circuit_breaker_trips: int = 0
    retries: int = 0


_resilience_metrics: dict[str, ResilienceMetrics] = defaultdict(ResilienceMetrics)


def get_resilience_metrics(key: str | None = None) -> dict[str, ResilienceMetrics]:
    """
    Get resilience metrics.

    Args:
        key: Optional key to get metrics for specific function

    Returns:
        Metrics dict or single metric
    """
    if key:
        return {key: _resilience_metrics[key]}
    return dict(_resilience_metrics)


def reset_resilience_metrics() -> None:
    """Reset all resilience metrics."""
    _resilience_metrics.clear()


def reset_circuit_breaker(key: str) -> None:
    """
    Reset specific circuit breaker.

    Args:
        key: Circuit breaker key (function name)
    """
    with _circuit_breakers_lock:
        if key in _circuit_breakers:
            _circuit_breakers[key].reset()
