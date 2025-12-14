"""
Merlya SSH - Circuit breaker implementation.

Provides circuit breaker pattern for SSH connection resilience.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from loguru import logger


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for SSH connections.

    Prevents cascade failures by opening the circuit after too many failures.
    """

    failure_threshold: int = 5  # Number of failures before opening
    timeout: int = 60  # Seconds to wait before trying half-open
    recovery_timeout: int = 30  # Time window for success rate calculation

    def __init__(self) -> None:
        """Initialize circuit breaker."""
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: float | None = None
        self._success_count: int = 0
        self._attempt_count: int = 0

    def can_execute(self) -> bool:
        """Check if commands can be executed through the circuit."""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            return self.time_until_retry() <= 0
        else:  # HALF_OPEN
            return True

    def record_failure(self) -> None:
        """Record a failure and update circuit state."""
        self.failure_count += 1
        self.last_failure_time = self._get_current_time()
        self._attempt_count += 1

        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._open_circuit()
        elif self.state == CircuitState.HALF_OPEN:
            self._open_circuit()

    def record_success(self) -> None:
        """Record a success and update circuit state."""
        self._success_count += 1
        self._attempt_count += 1

        if self.state == CircuitState.HALF_OPEN:
            self._close_circuit()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = max(0, self.failure_count - 1)

    def _open_circuit(self) -> None:
        """Open the circuit."""
        self.state = CircuitState.OPEN
        logger.warning(f"🔌 Circuit breaker opened (failures: {self.failure_count})")

    def _close_circuit(self) -> None:
        """Close the circuit."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self._success_count = 0
        self._attempt_count = 0
        logger.info("🔌 Circuit breaker closed")

    def time_until_retry(self) -> float:
        """Get time until next retry attempt (0 if ready)."""
        if self.state != CircuitState.OPEN or self.last_failure_time is None:
            return 0.0

        elapsed = self._get_current_time() - self.last_failure_time
        remaining = self.timeout - elapsed
        return max(0.0, remaining)

    def _get_current_time(self) -> float:
        """Get current time (mockable for testing)."""
        import time

        return time.time()
