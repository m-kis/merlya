"""
Robust Plan Executor with state management, parallelization, and error handling.

Executes multi-step plans with:
- State passing between steps
- Parallel execution of independent steps
- Automatic retry on transient failures
- Rollback on critical failures
- Progress tracking
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from merlya.core import StepStatus
from merlya.remediation.rollback import RollbackManager
from merlya.utils.logger import logger


@dataclass
class StepResult:
    """Result of executing a step."""
    step_id: int
    status: StepStatus
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    retries: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionContext:
    """
    Context shared across step executions.

    Allows steps to pass data to dependent steps.
    """
    results: Dict[int, StepResult] = field(default_factory=dict)
    shared_state: Dict[str, Any] = field(default_factory=dict)
    snapshots: List[str] = field(default_factory=list)  # Snapshot IDs for rollback

    def get_step_output(self, step_id: int) -> Any:
        """Get output from a specific step."""
        result = self.results.get(step_id)
        return result.output if result else None

    def set_shared(self, key: str, value: Any) -> None:
        """Set shared state value."""
        self.shared_state[key] = value

    def get_shared(self, key: str, default: Any = None) -> Any:
        """Get shared state value."""
        return self.shared_state.get(key, default)


class PlanExecutor:
    """
    Execute multi-step plans with robustness features.

    Features:
    - Parallel execution of independent steps
    - Automatic retry with exponential backoff
    - Rollback on failure
    - State management
    - Progress tracking
    """

    def __init__(
        self,
        tool_executor: Any = None,  # Function to execute tools
        rollback_manager: Optional[RollbackManager] = None,
        max_retries: int = 2,
        retry_delay: float = 1.0,
        enable_rollback: bool = True
    ):
        """
        Initialize plan executor.

        Args:
            tool_executor: Function to execute individual steps/tools
            rollback_manager: RollbackManager for undo on failure
            max_retries: Maximum retries per step
            retry_delay: Initial delay between retries (seconds)
            enable_rollback: Whether to automatically rollback on failure
        """
        self.tool_executor = tool_executor
        self.rollback_manager = rollback_manager
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_rollback = enable_rollback

    async def execute_plan(
        self,
        steps: List[Dict[str, Any]],
        preview: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a multi-step plan.

        Args:
            steps: List of step dictionaries
            preview: If True, only show what would be executed

        Returns:
            Execution summary
        """
        logger.info(f"Executing plan with {len(steps)} steps (preview={preview})")

        context = ExecutionContext()
        start_time = time.time()

        try:
            # Execute steps in optimal order
            results = await self._execute_steps(steps, context, preview)

            duration = time.time() - start_time
            success = all(r.status == StepStatus.COMPLETED for r in results.values())

            return {
                "success": success,
                "duration_sec": duration,
                "steps_completed": sum(1 for r in results.values() if r.status == StepStatus.COMPLETED),
                "steps_failed": sum(1 for r in results.values() if r.status == StepStatus.FAILED),
                "steps_skipped": sum(1 for r in results.values() if r.status == StepStatus.SKIPPED),
                "results": results,
                "context": context
            }

        except Exception as e:
            logger.error(f"Plan execution failed: {e}")

            # Rollback if enabled
            if self.enable_rollback and self.rollback_manager:
                await self._rollback_plan(context)

            return {
                "success": False,
                "error": str(e),
                "duration_sec": time.time() - start_time,
                "results": context.results
            }

    async def _execute_steps(
        self,
        steps: List[Dict[str, Any]],
        context: ExecutionContext,
        preview: bool
    ) -> Dict[int, StepResult]:
        """
        Execute steps with dependency resolution and parallelization.

        Args:
            steps: List of steps
            context: Execution context
            preview: Preview mode

        Returns:
            Dict of step results
        """
        # Track completed steps
        completed: Set[int] = set()
        remaining = {step["id"]: step for step in steps}

        while remaining:
            # Find steps ready to execute (dependencies met)
            ready_steps = [
                step for step in remaining.values()
                if all(dep in completed for dep in step.get("dependencies", []))
            ]

            if not ready_steps:
                # Deadlock - circular dependencies or missing deps
                logger.error("Plan execution deadlock - circular dependencies?")
                break

            # Separate parallelizable and sequential steps
            parallel_steps = [s for s in ready_steps if s.get("parallelizable", False)]
            sequential_steps = [s for s in ready_steps if not s.get("parallelizable", False)]

            # Execute sequential steps first
            for step in sequential_steps:
                result = await self._execute_single_step(step, context, preview)
                context.results[step["id"]] = result

                if result.status == StepStatus.COMPLETED:
                    completed.add(step["id"])
                elif result.status == StepStatus.FAILED:
                    # Critical failure - stop execution
                    logger.error(f"Step {step['id']} failed critically")
                    return context.results

                remaining.pop(step["id"])

            # Execute parallelizable steps concurrently
            if parallel_steps:
                tasks = [
                    self._execute_single_step(step, context, preview)
                    for step in parallel_steps
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for step, res in zip(parallel_steps, results, strict=False):
                    step_result: StepResult
                    if isinstance(res, Exception):
                        # Handle exceptions from asyncio.gather (excludes KeyboardInterrupt, SystemExit)
                        step_result = StepResult(
                            step_id=step["id"],
                            status=StepStatus.FAILED,
                            error=str(res)
                        )
                    elif isinstance(res, StepResult):
                        step_result = res
                    else:
                        # Unexpected return type - should not happen
                        logger.error(f"Unexpected result type from step {step['id']}: {type(res)}")
                        step_result = StepResult(
                            step_id=step["id"],
                            status=StepStatus.FAILED,
                            error=f"Unexpected result type: {type(res)}"
                        )

                    context.results[step["id"]] = step_result

                    if step_result.status == StepStatus.COMPLETED:
                        completed.add(step["id"])

                    remaining.pop(step["id"])

        return context.results

    async def _execute_single_step(
        self,
        step: Dict[str, Any],
        context: ExecutionContext,
        preview: bool
    ) -> StepResult:
        """
        Execute a single step with retry logic.

        Args:
            step: Step dict
            context: Execution context
            preview: Preview mode

        Returns:
            StepResult
        """
        step_id = step["id"]
        description = step.get("description", f"Step {step_id}")

        logger.info(f"Executing step {step_id}: {description}")

        if preview:
            # Preview mode - just show what would be executed
            return StepResult(
                step_id=step_id,
                status=StepStatus.SKIPPED,
                output=f"[PREVIEW] {description}"
            )

        # Create snapshot before critical operations
        if step.get("critical", False) and self.rollback_manager:
            snapshot_id = self._create_snapshot(step)
            if snapshot_id:
                context.snapshots.append(snapshot_id)

        # Execute with retry
        start_time = time.time()
        attempt = 0

        while attempt <= self.max_retries:
            try:
                # Execute the step
                output = await self._call_tool_executor(step, context)

                duration = int((time.time() - start_time) * 1000)

                return StepResult(
                    step_id=step_id,
                    status=StepStatus.COMPLETED,
                    output=output,
                    duration_ms=duration,
                    retries=attempt
                )

            except Exception as e:
                attempt += 1
                logger.warning(f"Step {step_id} failed (attempt {attempt}/{self.max_retries + 1}): {e}")

                if attempt > self.max_retries:
                    # All retries exhausted
                    duration = int((time.time() - start_time) * 1000)
                    return StepResult(
                        step_id=step_id,
                        status=StepStatus.FAILED,
                        error=str(e),
                        duration_ms=duration,
                        retries=attempt - 1
                    )

                # Exponential backoff
                await asyncio.sleep(self.retry_delay * (2 ** (attempt - 1)))

        # Unreachable but satisfies mypy - loop always returns
        return StepResult(step_id=step_id, status=StepStatus.FAILED, error="Unexpected loop exit")

    async def _call_tool_executor(
        self,
        step: Dict[str, Any],
        context: ExecutionContext
    ) -> Any:
        """
        Call tool executor with step data.

        Args:
            step: Step dict
            context: Execution context

        Returns:
            Step output
        """
        if not self.tool_executor:
            # No executor - just return step description
            return step.get("description", "")

        # Pass context to executor
        step_with_context = {
            **step,
            "context": context
        }

        # Execute
        if asyncio.iscoroutinefunction(self.tool_executor):
            return await self.tool_executor(step_with_context)
        else:
            return self.tool_executor(step_with_context)

    def _create_snapshot(self, step: Dict[str, Any]) -> Optional[str]:
        """
        Create snapshot before critical step.

        Args:
            step: Step dict

        Returns:
            Snapshot ID or None
        """
        if not self.rollback_manager:
            return None

        try:
            # Extract snapshot info from step
            target = step.get("target", "local")
            file_path = step.get("file_path")

            if file_path:
                snapshot_id = self.rollback_manager.create_snapshot(
                    target=target,
                    file_path=file_path,
                    description=f"Before step {step['id']}: {step.get('description', '')}"
                )
                return snapshot_id

        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")

        return None

    async def _rollback_plan(self, context: ExecutionContext) -> None:
        """
        Rollback all actions in reverse order.

        Args:
            context: Execution context with snapshots
        """
        logger.info("Rolling back plan execution")

        if not self.rollback_manager:
            logger.warning("No rollback manager available - skipping rollback")
            return

        for snapshot_id in reversed(context.snapshots):
            try:
                success = self.rollback_manager.restore_snapshot(snapshot_id)
                if success:
                    logger.info(f"Restored snapshot {snapshot_id}")
                else:
                    logger.error(f"Failed to restore snapshot {snapshot_id}")
            except Exception as e:
                logger.error(f"Rollback error for {snapshot_id}: {e}")
