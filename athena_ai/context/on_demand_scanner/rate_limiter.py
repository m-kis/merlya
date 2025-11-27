"""
Rate limiting for on-demand scanning.
"""
import asyncio
import threading
import time
from typing import Optional

from .config import ScanConfig


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, burst: int):
        """
        Initialize rate limiter.

        Args:
            rate: Requests per second
            burst: Maximum burst size

        Raises:
            ValueError: If rate is not a positive number or burst is not a positive integer
        """
        # Validate rate: must be a positive number
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            raise ValueError(f"rate must be a positive number, got {rate!r}")
        if rate <= 0:
            raise ValueError(f"rate must be greater than 0, got {rate}")

        # Validate burst: must be a positive integer
        if not isinstance(burst, int):
            try:
                burst = int(burst)
            except (TypeError, ValueError):
                raise ValueError(f"burst must be a positive integer, got {burst!r}")
        if burst <= 0:
            raise ValueError(f"burst must be greater than 0, got {burst}")

        self.rate = rate
        self.burst = burst
        self.tokens = float(self.burst)
        self.last_update = time.monotonic()
        self._lock: Optional[asyncio.Lock] = None  # Lazy init to avoid RuntimeError

    async def acquire(self):
        """Acquire a token, waiting if necessary.

        Uses a loop to ensure tokens are only consumed when >= 1,
        preventing negative token counts and rate limit violations.
        """
        # Lazy initialization of lock when event loop is running
        if self._lock is None:
            self._lock = asyncio.Lock()

        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

                # Need to wait for token - compute wait time
                wait_time = (1 - self.tokens) / self.rate

            # Sleep outside the lock to allow other callers to proceed
            await asyncio.sleep(wait_time)
            # Loop back to recheck tokens under lock before consuming


# Module-level shared RateLimiter to enforce global rate limits across all instances.
_shared_rate_limiter: Optional[RateLimiter] = None
_init_lock = threading.Lock()


def get_shared_rate_limiter(config: ScanConfig) -> RateLimiter:
    """Get or create the shared rate limiter."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:  # Fast path check
        with _init_lock:
            if _shared_rate_limiter is None:  # Double-checked locking
                _shared_rate_limiter = RateLimiter(config.requests_per_second, config.burst_size)
    return _shared_rate_limiter
