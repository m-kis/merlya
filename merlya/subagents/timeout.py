"""
Merlya Subagents - Activity-based Timeout.

Provides intelligent timeout that tracks activity instead of absolute time.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from loguru import logger

# Default timeout values
DEFAULT_IDLE_TIMEOUT_SECONDS = 60  # Cancel if no activity for 60s
DEFAULT_MAX_TIMEOUT_SECONDS = 600  # Absolute max of 10 minutes
MIN_IDLE_TIMEOUT_SECONDS = 10
MIN_MAX_TIMEOUT_SECONDS = 30


class ActivityTimeout:
    """Activity-based timeout manager.

    Unlike a simple timeout that cancels after X seconds total,
    this tracks the last activity and only cancels if idle for too long.

    This is useful for long-running tasks that make continuous progress
    but would be killed by a fixed timeout.

    Example:
        >>> async with ActivityTimeout(idle=30, max_timeout=300) as tracker:
        ...     # Long running operation
        ...     for item in items:
        ...         result = await process(item)
        ...         tracker.touch()  # Reset idle timer
        ...     return result

    Attributes:
        idle_timeout: Seconds of inactivity before timeout.
        max_timeout: Absolute maximum runtime.
        last_activity: Timestamp of last activity.
        start_time: Timestamp when execution started.
    """

    def __init__(
        self,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        max_timeout: float = DEFAULT_MAX_TIMEOUT_SECONDS,
        on_timeout: Callable[[], Any] | None = None,
    ) -> None:
        """
        Initialize the activity timeout.

        Args:
            idle_timeout: Seconds of inactivity before cancellation.
            max_timeout: Absolute maximum seconds before cancellation.
            on_timeout: Optional callback when timeout occurs.
        """
        self.idle_timeout = max(idle_timeout, MIN_IDLE_TIMEOUT_SECONDS)
        self.max_timeout = max(max_timeout, MIN_MAX_TIMEOUT_SECONDS)
        self.on_timeout = on_timeout

        self.start_time: float = 0.0
        self.last_activity: float = 0.0
        self._cancelled = False
        self._cancel_event: asyncio.Event | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._timeout_reason: str | None = None

    def touch(self) -> None:
        """Record activity - resets the idle timer."""
        self.last_activity = time.monotonic()

    @property
    def elapsed(self) -> float:
        """Get elapsed time since start."""
        if self.start_time == 0:
            return 0.0
        return time.monotonic() - self.start_time

    @property
    def idle_time(self) -> float:
        """Get time since last activity."""
        if self.last_activity == 0:
            return 0.0
        return time.monotonic() - self.last_activity

    @property
    def is_cancelled(self) -> bool:
        """Check if timeout has been triggered."""
        return self._cancelled

    @property
    def timeout_reason(self) -> str | None:
        """Get the reason for timeout (idle or max)."""
        return self._timeout_reason

    async def _monitor_loop(self) -> None:
        """Background task that monitors for timeout conditions."""
        check_interval = min(self.idle_timeout / 4, 5.0)  # Check frequently

        while not self._cancelled:
            await asyncio.sleep(check_interval)

            now = time.monotonic()
            elapsed = now - self.start_time
            idle = now - self.last_activity

            # Check max timeout
            if elapsed >= self.max_timeout:
                self._cancelled = True
                self._timeout_reason = f"max timeout ({self.max_timeout:.0f}s)"
                logger.warning(f"⏱️ ActivityTimeout: max timeout reached after {elapsed:.1f}s")
                break

            # Check idle timeout
            if idle >= self.idle_timeout:
                self._cancelled = True
                self._timeout_reason = f"idle timeout ({self.idle_timeout:.0f}s)"
                logger.warning(
                    f"⏱️ ActivityTimeout: idle timeout after {idle:.1f}s "
                    f"(last activity {self.idle_timeout:.0f}s ago)"
                )
                break

        # Signal cancellation
        if self._cancel_event:
            self._cancel_event.set()

        # Invoke callback
        if self._cancelled and self.on_timeout:
            try:
                result = self.on_timeout()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"⚠️ Timeout callback failed: {e}")

    async def __aenter__(self) -> ActivityTimeout:
        """Enter the context - start monitoring."""
        self.start_time = time.monotonic()
        self.last_activity = self.start_time
        self._cancelled = False
        self._timeout_reason = None
        self._cancel_event = asyncio.Event()

        # Start background monitor
        self._monitor_task = asyncio.create_task(self._monitor_loop())

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        """Exit the context - stop monitoring."""
        # Cancel the monitor task
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # If we were cancelled due to timeout, raise TimeoutError
        if self._cancelled and exc_type is None:
            raise TimeoutError(f"Activity timeout: {self._timeout_reason}")

        return False  # Don't suppress exceptions

    async def wait_or_timeout(self, coro: Any) -> Any:
        """
        Execute a coroutine with activity-based timeout monitoring.

        This runs the coroutine while the monitor checks for timeouts.
        The caller should call touch() periodically to signal progress.

        Args:
            coro: Coroutine to execute.

        Returns:
            Result of the coroutine.

        Raises:
            TimeoutError: If timeout occurs.
            asyncio.CancelledError: If externally cancelled.
        """
        # Create task for the coroutine
        task = asyncio.create_task(coro)

        try:
            # Wait for either task completion or cancellation
            while not task.done():
                if self._cancelled:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise TimeoutError(f"Activity timeout: {self._timeout_reason}")

                # Wait a bit before checking again
                await asyncio.sleep(0.1)

            return task.result()

        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise


def create_activity_timeout(
    skill_timeout: float | None = None,
    idle_ratio: float = 0.5,
    min_idle: float = MIN_IDLE_TIMEOUT_SECONDS,
) -> ActivityTimeout:
    """
    Create an ActivityTimeout with smart defaults based on skill timeout.

    Args:
        skill_timeout: Skill's configured timeout (used as max).
        idle_ratio: Ratio of max timeout to use as idle timeout.
        min_idle: Minimum idle timeout.

    Returns:
        Configured ActivityTimeout instance.
    """
    max_timeout = skill_timeout or DEFAULT_MAX_TIMEOUT_SECONDS
    idle_timeout = max(max_timeout * idle_ratio, min_idle)

    return ActivityTimeout(
        idle_timeout=idle_timeout,
        max_timeout=max_timeout,
    )
