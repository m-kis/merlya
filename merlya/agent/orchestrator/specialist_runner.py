"""
Specialist runner functions.

Contains logic for running specialists with retry and completion detection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps

from .completion import task_seems_complete
from .constants import MAX_SPECIALIST_RETRIES, SPECIALIST_LIMITS
from .models import DelegationResult, OrchestratorDeps

if TYPE_CHECKING:
    from pydantic_ai import RunContext


async def run_specialist_with_retry(
    ctx: RunContext[OrchestratorDeps],
    specialist_fn: object,
    specialist_type: Literal["diagnostic", "execution", "security", "query"],
    target: str,
    task: str,
    **kwargs: object,
) -> DelegationResult:
    """
    Run a specialist with retry logic for incomplete tasks.

    IMPORTANT: The tracker is NOT reset between retries. This ensures:
    - Loop detection persists across all attempts
    - Same commands won't be re-executed (detected as loops)
    - Previous execution context is preserved

    Args:
        ctx: Run context.
        specialist_fn: Specialist function to call.
        specialist_type: Type of specialist.
        target: Target host.
        task: Task description.
        **kwargs: Additional kwargs for specialist.

    Returns:
        DelegationResult from specialist.
    """
    tool_limit = SPECIALIST_LIMITS.get(specialist_type, 30)
    limits = UsageLimits(tool_calls_limit=tool_limit)
    previous_output = ""

    for attempt in range(MAX_SPECIALIST_RETRIES):
        # Check for loops BEFORE retrying - don't retry if we're stuck
        is_looping, loop_reason = ctx.deps.tracker.is_looping()
        if is_looping and attempt > 0:
            logger.warning(f"Loop detected, stopping retries: {loop_reason}")
            return DelegationResult(
                success=True,
                output=previous_output or f"Stopped due to loop: {loop_reason}",
                specialist=specialist_type,
                complete=False,
            )

        if attempt > 0:
            tracker_summary = ctx.deps.tracker.get_summary()
            logger.info(
                f"Retry {attempt + 1}/{MAX_SPECIALIST_RETRIES} for {specialist_type} "
                f"(tracker: {tracker_summary})"
            )

        # Build task with context from previous attempts
        current_task = task
        if previous_output:
            tracker_info = ctx.deps.tracker.get_summary()
            current_task = (
                f"{task}\n\n"
                f"Previous attempt context:\n{previous_output[:500]}\n\n"
                f"Commands already tried: {tracker_info}\n"
                f"IMPORTANT: Do not repeat commands that were already executed."
            )

        try:
            deps = SpecialistDeps(
                context=ctx.deps.context,
                tracker=ctx.deps.tracker,
                confirmation_state=ctx.deps.confirmation_state,
                target=target,
            )
            result = await specialist_fn(  # type: ignore[operator]
                deps=deps,
                task=current_task,
                usage_limits=limits,
                **kwargs,
            )

            if task_seems_complete(result):
                return DelegationResult(
                    success=True,
                    output=result,
                    specialist=specialist_type,
                    complete=True,
                )

            previous_output = result

            # Check for loops after execution
            is_looping, loop_reason = ctx.deps.tracker.is_looping()
            if is_looping:
                logger.warning(f"Loop detected after {specialist_type}: {loop_reason}")
                return DelegationResult(
                    success=True,
                    output=f"{result}\n\nStopped: {loop_reason}",
                    specialist=specialist_type,
                    complete=False,
                )

            logger.warning(f"Task may be incomplete after {specialist_type}")

        except Exception as e:
            logger.error(f"Specialist {specialist_type} failed: {e}")
            return DelegationResult(
                success=False,
                output=f"Error: {e}",
                specialist=specialist_type,
                complete=False,
            )

    return DelegationResult(
        success=True,
        output=previous_output or "Task completed with maximum retries",
        specialist=specialist_type,
        complete=False,
    )


async def run_specialist_once(
    ctx: RunContext[OrchestratorDeps],
    specialist_fn: object,
    specialist_type: Literal["diagnostic", "execution", "security", "query"],
    target: str,
    task: str,
    **kwargs: object,
) -> DelegationResult:
    """
    Run a specialist once without retry (for security/query).

    Args:
        ctx: Run context.
        specialist_fn: Specialist function to call.
        specialist_type: Type of specialist.
        target: Target host.
        task: Task description.
        **kwargs: Additional kwargs for specialist.

    Returns:
        DelegationResult from specialist.
    """
    tool_limit = SPECIALIST_LIMITS.get(specialist_type, 15)
    limits = UsageLimits(tool_calls_limit=tool_limit)

    try:
        deps = SpecialistDeps(
            context=ctx.deps.context,
            tracker=ctx.deps.tracker,
            confirmation_state=ctx.deps.confirmation_state,
            target=target,
        )
        result = await specialist_fn(  # type: ignore[operator]
            deps=deps,
            task=task,
            usage_limits=limits,
            **kwargs,
        )

        return DelegationResult(
            success=True,
            output=result,
            specialist=specialist_type,
            complete=True,
        )

    except Exception as e:
        logger.error(f"Specialist {specialist_type} failed: {e}", exc_info=True)
        return DelegationResult(
            success=False,
            output="Specialist encountered an error. Check logs for details.",
            specialist=specialist_type,
            complete=False,
        )
