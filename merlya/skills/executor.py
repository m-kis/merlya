"""
Merlya Skills - Executor.

Executes skills on hosts with tool filtering and timeout management.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.skills.models import HostResult, SkillConfig, SkillResult, SkillStatus

if TYPE_CHECKING:
    from merlya.config.policies import PolicyManager


class SkillExecutor:
    """Executes skills on hosts.

    Manages parallel execution across hosts with:
    - Tool filtering (only allowed tools)
    - Timeout enforcement
    - Result aggregation
    - Confirmation for destructive operations

    Example:
        >>> executor = SkillExecutor(policy_manager)
        >>> result = await executor.execute(skill, hosts=["web-01", "web-02"], task="check disk")
        >>> print(result.to_summary())
    """

    def __init__(
        self,
        policy_manager: PolicyManager | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        """
        Initialize the executor.

        Args:
            policy_manager: Policy manager for limits and confirmations.
            max_concurrent: Override max concurrent hosts (uses policy if None).
        """
        self.policy_manager = policy_manager
        self._max_concurrent = max_concurrent
        logger.debug("🎬 SkillExecutor initialized")

    @property
    def max_concurrent(self) -> int:
        """Get max concurrent executions."""
        if self._max_concurrent:
            return self._max_concurrent
        if self.policy_manager:
            return self.policy_manager.config.max_hosts_per_skill
        return 5  # Default

    async def execute(
        self,
        skill: SkillConfig,
        hosts: list[str],
        task: str,
        context: dict[str, Any] | None = None,
        confirm_callback: Any | None = None,
    ) -> SkillResult:
        """
        Execute a skill on multiple hosts.

        Args:
            skill: Skill configuration.
            hosts: List of host identifiers.
            task: Task description or user input.
            context: Additional context for execution.
            confirm_callback: Async callback for confirmations.

        Returns:
            SkillResult with aggregated results.
        """
        execution_id = str(uuid.uuid4())[:8]
        started_at = datetime.now(timezone.utc)

        logger.info(f"🎬 Executing skill '{skill.name}' on {len(hosts)} hosts (id={execution_id})")

        # Validate host count
        if self.policy_manager:
            is_valid, error = self.policy_manager.validate_hosts_count(len(hosts))
            if not is_valid:
                logger.warning(f"⚠️ {error}")
                return self._create_failed_result(
                    skill, execution_id, started_at, error or "Host count validation failed"
                )

        # Apply skill's max_hosts limit
        effective_hosts = hosts
        if len(hosts) > skill.max_hosts:
            logger.warning(
                f"⚠️ Limiting hosts from {len(hosts)} to skill max of {skill.max_hosts}"
            )
            effective_hosts = hosts[: skill.max_hosts]

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(min(self.max_concurrent, skill.max_hosts))

        # Execute on all hosts in parallel
        async def execute_on_host(host: str) -> HostResult:
            async with semaphore:
                return await self._execute_single(
                    skill=skill,
                    host=host,
                    task=task,
                    context=context,
                    confirm_callback=confirm_callback,
                )

        # Gather results
        host_results = await asyncio.gather(
            *[execute_on_host(h) for h in effective_hosts],
            return_exceptions=True,
        )

        # Process results
        processed_results: list[HostResult] = []
        for i, result in enumerate(host_results):
            if isinstance(result, Exception):
                processed_results.append(
                    HostResult(
                        host=effective_hosts[i],
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        # Calculate stats
        succeeded = sum(1 for r in processed_results if r.success)
        failed = len(processed_results) - succeeded

        # Determine status
        if failed == 0:
            status = SkillStatus.SUCCESS
        elif succeeded == 0:
            status = SkillStatus.FAILED
        else:
            status = SkillStatus.PARTIAL

        result = SkillResult(
            skill_name=skill.name,
            execution_id=execution_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            host_results=processed_results,
            total_hosts=len(effective_hosts),
            succeeded_hosts=succeeded,
            failed_hosts=failed,
        )

        logger.info(f"🎬 Skill '{skill.name}' completed: {result.to_summary()}")
        return result

    async def _execute_single(
        self,
        skill: SkillConfig,
        host: str,
        task: str,
        context: dict[str, Any] | None = None,
        confirm_callback: Any | None = None,
    ) -> HostResult:
        """
        Execute skill on a single host.

        Args:
            skill: Skill configuration.
            host: Host identifier.
            task: Task description.
            context: Additional context.
            confirm_callback: Confirmation callback.

        Returns:
            HostResult for this host.
        """
        start_time = time.perf_counter()
        tool_calls = 0

        try:
            # Apply timeout
            async with asyncio.timeout(skill.timeout_seconds):
                # TODO: Integrate with actual subagent execution
                # For now, this is a placeholder that simulates execution
                output = await self._simulate_execution(skill, host, task)
                tool_calls = 1  # Placeholder

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            return HostResult(
                host=host,
                success=True,
                output=output,
                duration_ms=duration_ms,
                tool_calls=tool_calls,
            )

        except TimeoutError:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(f"⏱️ Timeout on host '{host}' after {skill.timeout_seconds}s")
            return HostResult(
                host=host,
                success=False,
                error=f"Timeout after {skill.timeout_seconds}s",
                duration_ms=duration_ms,
                tool_calls=tool_calls,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"❌ Error on host '{host}': {e}")
            return HostResult(
                host=host,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                tool_calls=tool_calls,
            )

    async def _simulate_execution(
        self,
        skill: SkillConfig,
        host: str,
        task: str,
    ) -> str:
        """
        Simulate skill execution (placeholder).

        In real implementation, this would:
        1. Create a subagent with filtered tools
        2. Execute the task with the skill's system prompt
        3. Return the result

        Args:
            skill: Skill configuration.
            host: Host identifier.
            task: Task description.

        Returns:
            Simulated output.
        """
        # Simulate some work
        await asyncio.sleep(0.1)
        return f"[{skill.name}] Executed on {host}: {task[:50]}..."

    def _create_failed_result(
        self,
        skill: SkillConfig,
        execution_id: str,
        started_at: datetime,
        error: str,
    ) -> SkillResult:
        """Create a failed result without executing."""
        return SkillResult(
            skill_name=skill.name,
            execution_id=execution_id,
            status=SkillStatus.FAILED,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            duration_ms=0,
            host_results=[],
            total_hosts=0,
            succeeded_hosts=0,
            failed_hosts=0,
            summary=f"Execution failed: {error}",
        )

    async def check_confirmation(
        self,
        skill: SkillConfig,
        operation: str,
        confirm_callback: Any | None = None,
    ) -> bool:
        """
        Check if an operation requires confirmation.

        Args:
            skill: Skill configuration.
            operation: Operation type.
            confirm_callback: Async callback to get user confirmation.

        Returns:
            True if confirmed or no confirmation needed.
        """
        # Check skill's confirmation requirements
        op_lower = operation.lower()
        needs_confirm = any(op_lower.startswith(c) for c in skill.require_confirmation_for)

        if not needs_confirm:
            return True

        # Check policy manager
        if self.policy_manager and not self.policy_manager.should_confirm(operation):
            return True

        # Need confirmation
        if confirm_callback:
            return await confirm_callback(f"Confirm {operation}?")

        logger.warning(f"⚠️ Operation '{operation}' requires confirmation but no callback provided")
        return False

    def filter_tools(self, skill: SkillConfig, available_tools: list[str]) -> list[str]:
        """
        Filter available tools based on skill permissions.

        Args:
            skill: Skill configuration.
            available_tools: List of available tool names.

        Returns:
            List of allowed tools for this skill.
        """
        if not skill.tools_allowed:
            # No restrictions - all tools allowed
            return available_tools

        return [t for t in available_tools if t in skill.tools_allowed]
