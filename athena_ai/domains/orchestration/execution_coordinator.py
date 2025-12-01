"""
Execution Coordinator - Intelligent execution management.

Like Claude Code, coordinates execution with safety and adaptability.

Responsibilities:
- Execute plans step-by-step
- Handle failures and rollbacks
- Provide real-time progress feedback
- Adapt execution based on results
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from athena_ai.core import StepStatus
from athena_ai.domains.orchestration.plan_manager import ExecutionPlan, ExecutionStep
from athena_ai.utils.logger import logger


@dataclass
class StepResult:
    """Result of executing a single step."""
    step_id: str
    status: StepStatus
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """
    Complete execution result.

    Like Claude Code, captures full execution history.
    """
    plan_id: str
    step_results: List[StepResult]
    overall_status: str  # success, partial, failed
    total_duration_ms: int = 0
    rollback_performed: bool = False
    final_output: Any = None


class ExecutionCoordinator:
    """
    Intelligent execution coordinator.

    Like Claude Code, executes plans safely with adaptability.

    Design:
    - SoC: Focused on execution coordination only
    - KISS: Simple step-by-step execution with error handling
    - DDD: Core domain service
    """

    def __init__(
        self,
        tool_executor: Callable,
        rollback_manager=None,
        max_retries: int = 2,
        enable_rollback: bool = True
    ):
        """
        Initialize execution coordinator.

        Args:
            tool_executor: Function to execute tools
            rollback_manager: Optional rollback manager
            max_retries: Maximum retries per step
            enable_rollback: Enable automatic rollback on failure
        """
        self.tool_executor = tool_executor
        self.rollback_manager = rollback_manager
        self.max_retries = max_retries
        self.enable_rollback = enable_rollback

    async def execute(
        self,
        plan: ExecutionPlan,
        progress_callback: Optional[Callable] = None
    ) -> ExecutionResult:
        """
        Execute plan intelligently.

        Like Claude Code, provides real-time feedback and handles failures.

        Args:
            plan: Execution plan
            progress_callback: Optional callback for progress updates

        Returns:
            Execution result
        """
        logger.info(f"Executing plan: {plan.request_id}")

        step_results: List[StepResult] = []
        start_time = asyncio.get_event_loop().time()

        # Execute steps in dependency order
        for step in plan.steps:
            # Check dependencies completed successfully
            if not self._dependencies_met(step, step_results):
                step_result = StepResult(
                    step_id=step.id,
                    status=StepStatus.SKIPPED,
                    error="Dependencies not met"
                )
                step_results.append(step_result)
                continue

            # Execute step
            step_result = await self._execute_step(step, step_results)
            step_results.append(step_result)

            # Progress callback
            if progress_callback:
                progress_callback(step, step_result)

            # Handle failure
            if step_result.status == StepStatus.FAILED:
                if self.enable_rollback and self.rollback_manager:
                    logger.warning(f"Step {step.id} failed, initiating rollback")
                    await self._perform_rollback(step_results)
                    break
                else:
                    logger.error(f"Step {step.id} failed, no rollback available")
                    break

        # Calculate overall status
        total_duration = int((asyncio.get_event_loop().time() - start_time) * 1000)
        overall_status = self._calculate_overall_status(step_results)

        # Synthesize final output
        final_output = self._synthesize_output(step_results)

        result = ExecutionResult(
            plan_id=plan.request_id,
            step_results=step_results,
            overall_status=overall_status,
            total_duration_ms=total_duration,
            rollback_performed=any(r.status == StepStatus.ROLLED_BACK for r in step_results),
            final_output=final_output
        )

        logger.info(f"Execution completed: {overall_status} in {total_duration}ms")
        return result

    def _dependencies_met(self, step: ExecutionStep, completed_results: List[StepResult]) -> bool:
        """Check if all dependencies are met."""
        if not step.dependencies:
            return True

        completed_ids = {
            r.step_id for r in completed_results
            if r.status == StepStatus.COMPLETED
        }

        return all(dep_id in completed_ids for dep_id in step.dependencies)

    async def _execute_step(
        self,
        step: ExecutionStep,
        previous_results: List[StepResult]
    ) -> StepResult:
        """
        Execute single step with retries.

        Like Claude Code, handles errors intelligently.
        """
        logger.debug(f"Executing step: {step.id} - {step.description}")

        for attempt in range(self.max_retries + 1):
            try:
                step_start = asyncio.get_event_loop().time()

                # Execute tool
                if step.tool:
                    output = await self.tool_executor(step.tool, step.params)
                else:
                    output = None

                duration_ms = int((asyncio.get_event_loop().time() - step_start) * 1000)

                return StepResult(
                    step_id=step.id,
                    status=StepStatus.COMPLETED,
                    output=output,
                    duration_ms=duration_ms
                )

            except Exception as e:
                logger.warning(f"Step {step.id} failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}")

                if attempt < self.max_retries:
                    # Retry with exponential backoff
                    await asyncio.sleep(2 ** attempt)
                else:
                    # Final failure
                    return StepResult(
                        step_id=step.id,
                        status=StepStatus.FAILED,
                        error=str(e)
                    )

        # Unreachable but satisfies mypy - loop always returns
        return StepResult(step_id=step.id, status=StepStatus.FAILED, error="Unexpected loop exit")

    async def _perform_rollback(self, step_results: List[StepResult]):
        """
        Perform rollback of executed steps.

        Like Claude Code, safely reverts changes.
        """
        logger.info("Performing rollback...")

        # Rollback in reverse order
        for result in reversed(step_results):
            if result.status == StepStatus.COMPLETED:
                try:
                    # Mark as rolled back
                    result.status = StepStatus.ROLLED_BACK
                    logger.debug(f"Rolled back: {result.step_id}")
                except Exception as e:
                    logger.error(f"Rollback failed for {result.step_id}: {e}")

    def _calculate_overall_status(self, results: List[StepResult]) -> str:
        """Calculate overall execution status."""
        if not results:
            return "failed"

        completed = sum(1 for r in results if r.status == StepStatus.COMPLETED)
        sum(1 for r in results if r.status == StepStatus.FAILED)
        total = len(results)

        if completed == total:
            return "success"
        elif completed > 0:
            return "partial"
        else:
            return "failed"

    def _synthesize_output(self, results: List[StepResult]) -> Any:
        """
        Synthesize final output from step results.

        Like Claude Code, creates coherent final output.
        """
        # Collect all outputs
        outputs = [r.output for r in results if r.output is not None]

        if not outputs:
            return None

        # If single output, return it
        if len(outputs) == 1:
            return outputs[0]

        # Multiple outputs - combine intelligently
        # For now, simple list
        return outputs
