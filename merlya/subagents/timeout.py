"""
Merlya Subagents - Activity-based Timeout.

Provides intelligent timeout that tracks activity instead of absolute time.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

# Default timeout values
DEFAULT_IDLE_TIMEOUT_SECONDS = 60  # Cancel if no activity for 60s
DEFAULT_MAX_TIMEOUT_SECONDS = 600  # Absolute max of 10 minutes
MIN_IDLE_TIMEOUT_SECONDS = 10
MIN_MAX_TIMEOUT_SECONDS = 30

# Context variable for current activity tracker (allows tools to call touch())
_current_tracker: contextvars.ContextVar[ActivityTimeout | None] = contextvars.ContextVar(
    "activity_tracker", default=None
)


def get_current_tracker() -> ActivityTimeout | None:
    """Get the current activity tracker from context (if any)."""
    return _current_tracker.get()


def touch_activity() -> None:
    """
    Touch the current activity tracker (if any).

    Call this from tools to signal that work is being done.
    Safe to call even if no tracker is active.
    """
    tracker = _current_tracker.get()
    if tracker:
        tracker.touch()


class ActivityTimeout:
    """Activity-based timeout manager.

    Unlike a simple timeout that cancels after X seconds total,
    this tracks the last activity and only cancels if idle for too long.

    This is useful for long-running tasks that make continuous progress
    but would be killed by a fixed timeout.

    Usage with run():
        >>> tracker = ActivityTimeout(idle=30, max_timeout=300)
        >>> result = await tracker.run(my_coroutine())

    The tracker is set in context, so tools can call touch_activity()
    to signal they are doing work.

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
        self._timeout_reason: str | None = None
        self._task: asyncio.Task[Any] | None = None

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

    def _check_timeout(self) -> bool:
        """Check if timeout should trigger. Returns True if timed out."""
        now = time.monotonic()
        elapsed = now - self.start_time
        idle = now - self.last_activity

        # Check max timeout
        if elapsed >= self.max_timeout:
            self._cancelled = True
            self._timeout_reason = f"max timeout ({self.max_timeout:.0f}s)"
            logger.warning(f"⏱️ ActivityTimeout: max timeout reached after {elapsed:.1f}s")
            return True

        # Check idle timeout
        if idle >= self.idle_timeout:
            self._cancelled = True
            self._timeout_reason = f"idle timeout ({self.idle_timeout:.0f}s)"
            logger.warning(
                f"⏱️ ActivityTimeout: idle timeout after {idle:.1f}s "
                f"(no activity for {self.idle_timeout:.0f}s)"
            )
            return True

        return False

    async def run(self, coro: Any) -> Any:
        """
        Execute a coroutine with activity-based timeout.

        This is the preferred way to use ActivityTimeout.
        The tracker is set in context so tools can call touch_activity().

        Args:
            coro: Coroutine to execute.

        Returns:
            Result of the coroutine.

        Raises:
            TimeoutError: If timeout occurs (idle or max).
            asyncio.CancelledError: If externally cancelled.
        """
        # Initialize timing
        self.start_time = time.monotonic()
        self.last_activity = self.start_time
        self._cancelled = False
        self._timeout_reason = None

        # Set this tracker in context so tools can call touch_activity()
        token = _current_tracker.set(self)

        # Create task for the coroutine
        self._task = asyncio.create_task(coro)

        # Check interval - frequently enough to catch timeouts
        check_interval = min(self.idle_timeout / 4, 2.0)

        try:
            while not self._task.done():
                # Wait for task or check interval
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(self._task),
                        timeout=check_interval,
                    )

                # Check if we should timeout
                if not self._task.done() and self._check_timeout():
                    # Cancel the task
                    self._task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._task

                    # Invoke callback if set
                    if self.on_timeout:
                        try:
                            result = self.on_timeout()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.warning(f"⚠️ Timeout callback failed: {e}")

                    raise TimeoutError(f"Activity timeout: {self._timeout_reason}")

            # Task completed successfully
            return self._task.result()

        except asyncio.CancelledError:
            # External cancellation
            if self._task and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            raise

        finally:
            # Reset context
            _current_tracker.reset(token)
            self._task = None


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
