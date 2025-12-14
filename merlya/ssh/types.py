"""
Merlya SSH - Type definitions.

Common types used across SSH modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from asyncssh import SSHClientConnection


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for SSH connections.

    Prevents cascade failures by tracking errors and temporarily
    blocking requests to unhealthy hosts.
    """

    failure_threshold: int = 5  # Failures before opening circuit
    recovery_timeout: int = 60  # Seconds before trying again
    half_open_max_calls: int = 1  # Calls allowed in half-open state

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: datetime | None = None
    half_open_calls: int = 0

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("🔌 Circuit breaker: recovered, closing circuit")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_calls = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(UTC)

        if self.state == CircuitState.HALF_OPEN:
            logger.warning("🔌 Circuit breaker: still failing, reopening circuit")
            self.state = CircuitState.OPEN
            self.half_open_calls = 0
        elif self.failure_count >= self.failure_threshold:
            logger.warning(f"🔌 Circuit breaker: {self.failure_count} failures, opening circuit")
            self.state = CircuitState.OPEN

    def can_execute(self) -> bool:
        """Check if a call can be made."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.now(UTC) - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    logger.info("🔌 Circuit breaker: testing recovery (half-open)")
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    return True
            return False

        # Half-open: allow limited calls
        if self.half_open_calls < self.half_open_max_calls:
            self.half_open_calls += 1
            return True
        return False

    def time_until_retry(self) -> int | None:
        """Return seconds until circuit may allow requests, or None if closed."""
        if self.state == CircuitState.CLOSED:
            return None
        if self.state == CircuitState.OPEN and self.last_failure_time:
            elapsed = (datetime.now(UTC) - self.last_failure_time).total_seconds()
            remaining = self.recovery_timeout - elapsed
            return max(0, int(remaining))
        return 0


@dataclass
class SSHResult:
    """Result of an SSH command execution."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass
class SSHConnectionOptions:
    """SSH connection configuration options."""

    port: int = 22
    jump_host: str | None = None
    jump_port: int | None = None
    jump_username: str | None = None
    jump_private_key: str | None = None
    connect_timeout: int | None = None


# Transient error patterns that warrant retry
TRANSIENT_ERROR_PATTERNS = (
    "connection reset",
    "broken pipe",
    "connection closed",
    "network is unreachable",
    "no route to host",
    "resource temporarily unavailable",
    "open failed",
    "channel open failed",
    "errno 54",  # Connection reset by peer (macOS)
    "errno 104",  # Connection reset by peer (Linux)
    "errno 32",  # Broken pipe
)


@dataclass
class SSHConnection:
    """Wrapper for an SSH connection with timeout management."""

    host: str
    connection: SSHClientConnection | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    timeout: int = 600
    _health_check_interval: int = 30  # Seconds between health checks
    _last_health_check: datetime | None = None
    _is_healthy: bool = True

    def is_alive(self) -> bool:
        """
        Check if connection is still valid (synchronous, timeout-based).

        For actual TCP state verification, use is_alive_async().
        """
        if self.connection is None:
            return False
        if not self._is_healthy:
            return False
        now = datetime.now(UTC)
        return not now - self.last_used > timedelta(seconds=self.timeout)

    async def is_alive_async(self) -> bool:
        """
        Check if connection is truly alive by testing TCP state.

        This method actually probes the connection rather than just
        checking the timeout. Use when you need to verify the connection
        is still responsive.
        """
        if self.connection is None:
            return False

        # Check timeout first (fast path)
        now = datetime.now(UTC)
        if now - self.last_used > timedelta(seconds=self.timeout):
            return False

        # Skip health check if recently verified
        if self._last_health_check:
            since_check = (now - self._last_health_check).total_seconds()
            if since_check < self._health_check_interval and self._is_healthy:
                return True

        # Actually probe the connection
        try:
            # Run a minimal command to test connection
            result = await asyncio.wait_for(
                self.connection.run("echo 1", check=False),
                timeout=5.0,
            )
            self._is_healthy = result.exit_status == 0
            self._last_health_check = datetime.now(UTC)

            if not self._is_healthy:
                logger.debug(f"🔌 Connection to {self.host} is unhealthy")

            return self._is_healthy

        except (TimeoutError, Exception) as e:
            logger.debug(f"🔌 Connection probe failed for {self.host}: {e}")
            self._is_healthy = False
            self._last_health_check = datetime.now(UTC)
            return False

    def mark_unhealthy(self) -> None:
        """Mark connection as unhealthy (for cleanup)."""
        self._is_healthy = False

    def refresh_timeout(self) -> None:
        """Refresh the timeout."""
        self.last_used = datetime.now(UTC)

    async def close(self) -> None:
        """Close the connection."""
        if self.connection:
            self.connection.close()
            try:
                await asyncio.wait_for(self.connection.wait_closed(), timeout=10.0)
            except TimeoutError:
                logger.warning("⚠️ Connection close timeout after 10s")
            self.connection = None
            self._is_healthy = False


def is_transient_error(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in TRANSIENT_ERROR_PATTERNS)
