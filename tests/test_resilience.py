"""
Unit tests for resilience module (circuit breaker, retry).

Tests:
- Circuit breaker state transitions
- Thread safety of global circuit breaker registry
- Retry with exponential backoff
- Metrics tracking
"""

from __future__ import annotations

import asyncio

import pytest

from merlya.core.metrics import get_registry, reset_metrics
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


@pytest.mark.asyncio
async def test_circuit_breaker_closed_state() -> None:
    """Test circuit breaker starts in CLOSED state."""
    config = CircuitBreakerConfig(failure_threshold=3)
    breaker = CircuitBreaker(config)

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures() -> None:
    """Test circuit breaker opens after failure threshold."""
    config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=1)
    breaker = CircuitBreaker(config)

    async def failing_func() -> str:
        raise ValueError("Test error")

    # Should fail 3 times and open circuit
    for _ in range(3):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN
    assert breaker.failure_count == 3


@pytest.mark.asyncio
async def test_circuit_breaker_rejects_when_open() -> None:
    """Test circuit breaker rejects calls when open."""
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1)
    breaker = CircuitBreaker(config)

    async def failing_func() -> str:
        raise ValueError("Test error")

    # Open the circuit
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN

    # Should reject immediately without calling function
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(failing_func)


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_after_timeout() -> None:
    """Test circuit breaker transitions to HALF_OPEN after recovery timeout."""
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
    breaker = CircuitBreaker(config)

    async def failing_func() -> str:
        raise ValueError("Test error")

    # Open the circuit
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

    assert breaker.state == CircuitState.OPEN

    # Wait for recovery timeout
    await asyncio.sleep(0.2)

    # Should transition to HALF_OPEN on next call
    async def success_func() -> str:
        return "success"

    result = await breaker.call(success_func)
    assert result == "success"
    # Should be in HALF_OPEN after first success
    assert breaker.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)


@pytest.mark.asyncio
async def test_circuit_breaker_closes_after_successes() -> None:
    """Test circuit breaker closes after success threshold in HALF_OPEN."""
    config = CircuitBreakerConfig(
        failure_threshold=2, recovery_timeout=0.1, success_threshold=2
    )
    breaker = CircuitBreaker(config)

    async def failing_func() -> str:
        raise ValueError("Test error")

    async def success_func() -> str:
        return "success"

    # Open the circuit
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

    await asyncio.sleep(0.2)

    # Succeed twice to close circuit
    await breaker.call(success_func)
    await breaker.call(success_func)

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_decorator() -> None:
    """Test circuit breaker decorator works correctly."""
    call_count = 0

    @circuit_breaker(failure_threshold=3, recovery_timeout=1)
    async def test_func(should_fail: bool = False) -> str:
        nonlocal call_count
        call_count += 1
        if should_fail:
            raise ValueError("Test error")
        return "success"

    # Should succeed
    result = await test_func(should_fail=False)
    assert result == "success"
    assert call_count == 1

    # Fail 3 times to open circuit
    for _ in range(3):
        with pytest.raises(ValueError):
            await test_func(should_fail=True)

    # Circuit should be open, rejects without calling
    call_count_before = call_count
    with pytest.raises(CircuitBreakerOpenError):
        await test_func(should_fail=False)

    # Function not called when circuit is open
    assert call_count == call_count_before


@pytest.mark.asyncio
async def test_retry_decorator_success() -> None:
    """Test retry decorator succeeds on first attempt."""
    call_count = 0

    @retry(max_attempts=3, initial_delay=0.01)
    async def test_func() -> str:
        nonlocal call_count
        call_count += 1
        return "success"

    result = await test_func()
    assert result == "success"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_decorator_retries_on_failure() -> None:
    """Test retry decorator retries on transient failures."""
    call_count = 0

    @retry(max_attempts=3, initial_delay=0.01)
    async def test_func() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("Transient error")
        return "success"

    result = await test_func()
    assert result == "success"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_decorator_exhausts_attempts() -> None:
    """Test retry decorator raises after max attempts."""
    call_count = 0

    @retry(max_attempts=3, initial_delay=0.01)
    async def test_func() -> str:
        nonlocal call_count
        call_count += 1
        raise ValueError("Persistent error")

    with pytest.raises(ValueError, match="Persistent error"):
        await test_func()

    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exponential_backoff() -> None:
    """Test retry uses exponential backoff."""
    import time

    call_times: list[float] = []

    @retry(max_attempts=3, initial_delay=0.05, exponential_base=2.0)
    async def test_func() -> str:
        call_times.append(time.time())
        raise ValueError("Test error")

    with pytest.raises(ValueError):
        await test_func()

    # Should have 3 attempts
    assert len(call_times) == 3

    # Verify exponential backoff (roughly)
    delay1 = call_times[1] - call_times[0]
    delay2 = call_times[2] - call_times[1]

    # delay2 should be roughly 2x delay1 (exponential base=2)
    assert delay2 > delay1 * 1.5  # Allow some variance


@pytest.mark.asyncio
async def test_reset_circuit_breaker() -> None:
    """Test resetting a specific circuit breaker."""

    @circuit_breaker(failure_threshold=2, key="test_breaker")
    async def test_func(should_fail: bool = False) -> str:
        if should_fail:
            raise ValueError("Test error")
        return "success"

    # Open the circuit
    for _ in range(2):
        with pytest.raises(ValueError):
            await test_func(should_fail=True)

    # Should be open
    with pytest.raises(CircuitBreakerOpenError):
        await test_func(should_fail=False)

    # Reset the breaker
    reset_circuit_breaker("test_breaker")

    # Should work again
    result = await test_func(should_fail=False)
    assert result == "success"


def test_reset_resilience_metrics() -> None:
    """Test resetting resilience metrics."""
    # Reset
    reset_resilience_metrics()

    # Should be empty
    metrics_after = get_resilience_metrics()
    assert len(metrics_after) == 0


@pytest.mark.asyncio
async def test_retry_tracks_metrics() -> None:
    """Test retry decorator tracks metrics for retry attempts."""
    reset_metrics()  # Clear metrics first

    call_count = 0

    @retry(max_attempts=3, initial_delay=0.01)
    async def test_func() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Transient error")
        return "success"

    result = await test_func()
    assert result == "success"
    assert call_count == 3

    # Check metrics were tracked
    registry = get_registry()
    all_metrics = registry.get_all()

    counters = all_metrics["counters"]
    assert "merlya_retry_attempts_total" in counters

    # Should have tracked 2 retry attempts (not the first attempt, only retries)
    # Note: labels are sorted alphabetically, so "attempt" comes before "function"
    labels = counters["merlya_retry_attempts_total"]["labels"]
    assert "attempt=1,function=test_func" in labels
    assert labels["attempt=1,function=test_func"] == 1
    assert "attempt=2,function=test_func" in labels
    assert labels["attempt=2,function=test_func"] == 1
