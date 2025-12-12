"""
Merlya Subagents - Orchestrator.

Manages parallel execution of subagents across multiple hosts.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.subagents.factory import SubagentFactory
from merlya.subagents.results import AggregatedResults, SubagentResult, SubagentStatus
from merlya.subagents.timeout import ActivityTimeout

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.skills.models import SkillConfig

# Constants
DEFAULT_MAX_CONCURRENT = 5
MIN_MAX_CONCURRENT = 1
MAX_MAX_CONCURRENT = 20

# Timeout configuration
# Max timeout: absolute maximum execution time (10 minutes)
DEFAULT_MAX_TIMEOUT_SECONDS = 600
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 3600  # 1 hour max

# Idle timeout: no activity for this long = stuck (60 seconds)
DEFAULT_IDLE_TIMEOUT_SECONDS = 60
IDLE_TIMEOUT_RATIO = 0.5  # idle = max * ratio (if max < default idle)


class SubagentOrchestrator:
    """Orchestrates parallel execution of subagents across hosts.

    Uses asyncio.gather with semaphore-based concurrency control
    to execute tasks on multiple hosts in parallel.

    Example:
        >>> orchestrator = SubagentOrchestrator(context, max_concurrent=5)
        >>> results = await orchestrator.run_on_hosts(
        ...     hosts=["web-01", "web-02", "web-03"],
        ...     task="check disk usage",
        ...     skill=disk_audit_skill,
        ... )
        >>> print(results.to_summary())
    """

    def __init__(
        self,
        context: SharedContext,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        model: str | None = None,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            context: Shared context with config and repositories.
            max_concurrent: Maximum concurrent subagent executions.
            model: Model to use for subagents.

        Raises:
            ValueError: If max_concurrent is out of valid range.
        """
        if not MIN_MAX_CONCURRENT <= max_concurrent <= MAX_MAX_CONCURRENT:
            raise ValueError(
                f"max_concurrent must be between {MIN_MAX_CONCURRENT} and {MAX_MAX_CONCURRENT}"
            )

        self.context = context
        self.max_concurrent = max_concurrent
        self.model = model

        # Create factory
        self.factory = SubagentFactory(context, model=model)

        # Concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # Tracking with thread-safe lock
        self._active_executions: dict[str, str] = {}  # execution_id -> status
        self._executions_lock = asyncio.Lock()

        logger.debug(f"🎼 SubagentOrchestrator initialized (max_concurrent={max_concurrent})")

    async def run_on_hosts(
        self,
        hosts: list[str],
        task: str,
        skill: SkillConfig | None = None,
        timeout: int | None = None,
        on_progress: Any | None = None,
    ) -> AggregatedResults:
        """
        Execute a task in parallel on multiple hosts.

        Args:
            hosts: List of host identifiers.
            task: Task description to execute.
            skill: Optional skill configuration for system prompt and tools.
            timeout: Timeout per host in seconds (default from skill or 120s).
            on_progress: Optional async callback(host, status, result) for progress.

        Returns:
            AggregatedResults with outcomes from all hosts.
        """
        if not hosts:
            logger.warning("🎼 No hosts provided for execution")
            return AggregatedResults(results=[])

        execution_id = str(uuid.uuid4())[:8]
        started_at = datetime.now(UTC)

        # Determine and validate max timeout
        effective_timeout: int | float = (
            timeout if timeout is not None else DEFAULT_MAX_TIMEOUT_SECONDS
        )
        if timeout is None and skill:
            skill_timeout = getattr(skill, "timeout_seconds", None)
            if isinstance(skill_timeout, (int, float)):
                effective_timeout = skill_timeout

        # Clamp timeout to valid range (also handles None/invalid values from above)
        if (
            not isinstance(effective_timeout, (int, float))
            or effective_timeout < MIN_TIMEOUT_SECONDS
        ):
            logger.warning(
                f"Timeout {effective_timeout}s too low, using minimum {MIN_TIMEOUT_SECONDS}s"
            )
            effective_timeout = MIN_TIMEOUT_SECONDS
        elif effective_timeout > MAX_TIMEOUT_SECONDS:
            logger.warning(
                f"Timeout {effective_timeout}s too high, using maximum {MAX_TIMEOUT_SECONDS}s"
            )
            effective_timeout = MAX_TIMEOUT_SECONDS

        # Calculate idle timeout (proportional to max, but capped at default)
        idle_timeout = min(
            max(effective_timeout * IDLE_TIMEOUT_RATIO, MIN_TIMEOUT_SECONDS),
            DEFAULT_IDLE_TIMEOUT_SECONDS,
        )

        logger.info(
            f"🎼 Starting parallel execution {execution_id} on {len(hosts)} hosts "
            f"(concurrent={self.max_concurrent}, max={effective_timeout}s, idle={idle_timeout}s)"
        )

        async with self._executions_lock:
            self._active_executions[execution_id] = "running"

        # Execute on all hosts in parallel
        async def run_one(host: str) -> SubagentResult:
            async with self._semaphore:
                return await self._execute_on_host(
                    host=host,
                    task=task,
                    skill=skill,
                    max_timeout=effective_timeout,
                    idle_timeout=idle_timeout,
                    execution_id=execution_id,
                    on_progress=on_progress,
                )

        start_time = time.perf_counter()

        # Gather results (return_exceptions=True to capture all outcomes)
        raw_results = await asyncio.gather(
            *[run_one(h) for h in hosts],
            return_exceptions=True,
        )

        total_duration_ms = int((time.perf_counter() - start_time) * 1000)
        completed_at = datetime.now(UTC)

        # Process results
        results: list[SubagentResult] = []
        for i, raw_result in enumerate(raw_results):
            if isinstance(raw_result, Exception):
                # Convert exception to SubagentResult
                results.append(
                    SubagentResult(
                        host=hosts[i],
                        success=False,
                        status=SubagentStatus.FAILED,
                        error=str(raw_result),
                    )
                )
            else:
                # raw_result is SubagentResult (not an exception)
                assert isinstance(raw_result, SubagentResult)
                results.append(raw_result)

        async with self._executions_lock:
            self._active_executions[execution_id] = "completed"

        # Create aggregated results
        aggregated = AggregatedResults(
            results=results,
            execution_id=execution_id,
            skill_name=skill.name if skill else None,
            task=task,
            started_at=started_at,
            completed_at=completed_at,
            total_duration_ms=total_duration_ms,
        )

        # Compute totals
        aggregated.compute_totals()

        logger.info(f"🎼 Execution {execution_id} completed: {aggregated.to_summary()}")

        return aggregated

    async def _execute_on_host(
        self,
        host: str,
        task: str,
        skill: SkillConfig | None,
        max_timeout: float,
        idle_timeout: float,
        execution_id: str,  # noqa: ARG002 - Part of public API, may be used in future
        on_progress: Any | None = None,
    ) -> SubagentResult:
        """
        Execute task on a single host with activity-based timeout.

        Uses ActivityTimeout to distinguish between:
        - Idle timeout: No activity for X seconds (stuck)
        - Max timeout: Absolute maximum runtime (safety limit)

        Args:
            host: Host identifier.
            task: Task to execute.
            skill: Skill configuration.
            max_timeout: Absolute maximum timeout in seconds.
            idle_timeout: Idle timeout in seconds (no activity = stuck).
            execution_id: Parent execution ID.
            on_progress: Progress callback.

        Returns:
            SubagentResult for this host.
        """
        started_at = datetime.now(UTC)
        start_time = time.perf_counter()

        # Notify progress: starting
        if on_progress:
            try:
                await on_progress(host, "starting", None)
            except Exception as e:
                logger.warning(f"⚠️ Progress callback failed for host {host}: {e}")

        try:
            # Create subagent for this host
            subagent = self.factory.create(
                host=host,
                skill=skill,
                task=task,
            )

            # Execute with activity-based timeout
            # The timeout monitors both idle time (no activity) and max runtime
            # Tools should call touch_activity() to signal progress
            timeout_tracker = ActivityTimeout(
                idle_timeout=idle_timeout,
                max_timeout=max_timeout,
            )
            run_result = await timeout_tracker.run(subagent.run(task))

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            completed_at = datetime.now(UTC)

            result = SubagentResult(
                host=host,
                subagent_id=subagent.subagent_id,
                success=run_result.success,
                status=SubagentStatus.SUCCESS if run_result.success else SubagentStatus.FAILED,
                output=run_result.output,
                error=run_result.error,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                raw_output=run_result.to_dict(),
            )

            # Notify progress: completed
            if on_progress:
                try:
                    await on_progress(host, "completed", result)
                except Exception as e:
                    logger.warning(f"⚠️ Progress callback failed for host {host}: {e}")

            logger.debug(f"🎼 Host {host} completed in {duration_ms}ms")
            return result

        except TimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            # Extract timeout reason from exception message
            timeout_reason = str(e) if str(e) else f"after {max_timeout}s"
            logger.warning(f"⏱️ Host {host} timed out: {timeout_reason}")

            result = SubagentResult(
                host=host,
                success=False,
                status=SubagentStatus.TIMEOUT,
                error=f"Execution timed out: {timeout_reason}",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=duration_ms,
            )

            # Notify progress: timeout
            if on_progress:
                try:
                    await on_progress(host, "timeout", result)
                except Exception as e:
                    logger.warning(f"⚠️ Progress callback failed for host {host}: {e}")

            return result

        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(f"🚫 Host {host} execution cancelled")

            result = SubagentResult(
                host=host,
                success=False,
                status=SubagentStatus.CANCELLED,
                error="Execution cancelled",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=duration_ms,
            )

            # Notify progress: cancelled
            if on_progress:
                try:
                    await on_progress(host, "cancelled", result)
                except Exception as e:
                    logger.warning(f"⚠️ Progress callback failed for host {host}: {e}")

            # Re-raise to propagate cancellation properly
            raise

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"❌ Host {host} failed: {e}")

            result = SubagentResult(
                host=host,
                success=False,
                status=SubagentStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=duration_ms,
            )

            # Notify progress: failed
            if on_progress:
                try:
                    await on_progress(host, "failed", result)
                except Exception as e2:
                    logger.warning(f"⚠️ Progress callback failed for host {host}: {e2}")

            return result

    async def run_on_host(
        self,
        host: str,
        task: str,
        skill: SkillConfig | None = None,
        timeout: int | None = None,
    ) -> SubagentResult:
        """
        Execute a task on a single host.

        Convenience method for single-host execution.

        Args:
            host: Host identifier.
            task: Task description.
            skill: Optional skill configuration.
            timeout: Timeout in seconds.

        Returns:
            SubagentResult for the host.
        """
        results = await self.run_on_hosts(
            hosts=[host],
            task=task,
            skill=skill,
            timeout=timeout,
        )
        return (
            results.results[0]
            if results.results
            else SubagentResult(
                host=host,
                success=False,
                status=SubagentStatus.FAILED,
                error="No result returned",
            )
        )

    async def get_active_executions(self) -> dict[str, str]:
        """Get currently active execution IDs and their status."""
        async with self._executions_lock:
            return dict(self._active_executions)

    async def clear_execution_history(self) -> None:
        """Clear execution history."""
        async with self._executions_lock:
            self._active_executions.clear()
