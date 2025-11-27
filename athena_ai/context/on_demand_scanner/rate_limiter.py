"""
Rate limiting for on-demand scanning.
"""
import asyncio
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
        """
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return

            # Need to wait for token - compute wait time and release lock before sleeping
            wait_time = (1 - self.tokens) / self.rate

        # Sleep outside the lock to allow other callers to proceed
        await asyncio.sleep(wait_time)

        # Reacquire lock and recompute tokens based on current time
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            # Consume one token (may go slightly negative if contention, but that's fine)
            self.tokens -= 1


# Module-level shared RateLimiter to enforce global rate limits across all instances.
_shared_rate_limiter: Optional[RateLimiter] = None


def get_shared_rate_limiter(config: ScanConfig) -> RateLimiter:
    """Get or create the shared rate limiter."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:
        _shared_rate_limiter = RateLimiter(config.requests_per_second, config.burst_size)
    return _shared_rate_limiter
