"""
Merlya Skills - Executor.

Executes skills on hosts with tool filtering and timeout management.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.skills.models import (
    HostResult,
    SkillConfig,
    SkillResult,
    SkillStatus,
)

if TYPE_CHECKING:
    from merlya.audit.logger import AuditLogger
    from merlya.config.policies import PolicyManager
    from merlya.core.context import SharedContext
    from merlya.subagents.orchestrator import SubagentOrchestrator


class SkillExecutor:
    """Executes skills on hosts.

    Manages parallel execution across hosts with:
    - Tool filtering (only allowed tools)
    - Timeout enforcement
    - Result aggregation
    - Confirmation for destructive operations
    - Integration with SubagentOrchestrator for real execution

    Example:
        >>> executor = SkillExecutor(context, policy_manager)
        >>> result = await executor.execute(skill, hosts=["web-01", "web-02"], task="check disk")
        >>> print(result.to_summary())
    """

    def __init__(
        self,
        context: SharedContext | None = None,
        policy_manager: PolicyManager | None = None,
        max_concurrent: int | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        """
        Initialize the executor.

        Args:
            context: Shared context for subagent creation.
            policy_manager: Policy manager for limits and confirmations.
            max_concurrent: Override max concurrent hosts (uses policy if None).
            audit_logger: Optional audit logger for operation logging.
        """
        self.context = context
        self.policy_manager = policy_manager
        self._max_concurrent = max_concurrent
        self._orchestrator: SubagentOrchestrator | None = None
        self._audit_logger = audit_logger
        logger.debug("🎬 SkillExecutor initialized")

    @property
    def max_concurrent(self) -> int:
        """Get max concurrent executions."""
        if self._max_concurrent:
            return self._max_concurrent
        if self.policy_manager:
            return self.policy_manager.config.max_hosts_per_skill
        return 5  # Default

    @property
    def orchestrator(self) -> SubagentOrchestrator | None:
        """Get or create the subagent orchestrator (lazy initialization)."""
        if self._orchestrator is None and self.context is not None:
            from merlya.subagents.orchestrator import SubagentOrchestrator

            self._orchestrator = SubagentOrchestrator(
                context=self.context,
                max_concurrent=self.max_concurrent,
            )
        return self._orchestrator

    @property
    def has_real_execution(self) -> bool:
        """Check if real subagent execution is available."""
        return self.context is not None

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
        started_at = datetime.now(UTC)

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
            logger.warning(f"⚠️ Limiting hosts from {len(hosts)} to skill max of {skill.max_hosts}")
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
                    _context=context,
                    _confirm_callback=confirm_callback,
                )

        # Gather results
        host_results = await asyncio.gather(
            *[execute_on_host(h) for h in effective_hosts],
            return_exceptions=True,
        )

        # Process results
        processed_results: list[HostResult] = []
        for i, raw_host_result in enumerate(host_results):
            if isinstance(raw_host_result, Exception):
                processed_results.append(
                    HostResult(
                        host=effective_hosts[i],
                        success=False,
                        error=str(raw_host_result),
                    )
                )
            else:
                # raw_host_result is HostResult (not an exception)
                assert isinstance(raw_host_result, HostResult)
                processed_results.append(raw_host_result)

        completed_at = datetime.now(UTC)
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

        skill_result = SkillResult(
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

        logger.info(f"🎬 Skill '{skill.name}' completed: {skill_result.to_summary()}")

        # Audit logging
        if self._audit_logger:
            try:
                await self._audit_logger.log_skill(
                    skill_name=skill.name,
                    hosts=effective_hosts,
                    task=task,
                    success=(status != SkillStatus.FAILED),
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ Audit logging failed for skill '{skill.name}' "
                    f"(hosts={effective_hosts}, task={task!r}): {e}"
                )

        return skill_result

    async def _execute_single(
        self,
        skill: SkillConfig,
        host: str,
        task: str,
        _context: dict[str, Any] | None = None,
        _confirm_callback: Any | None = None,
    ) -> HostResult:
        """
        Execute skill on a single host.

        Uses SubagentOrchestrator if context is available,
        otherwise falls back to simulation mode.

        Note: Timeout is now handled by the orchestrator using ActivityTimeout,
        which provides idle-based timeout detection (not just absolute time).

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
            # Use real subagent execution if orchestrator is available
            # Timeout is handled by orchestrator with ActivityTimeout
            if self.orchestrator is not None:
                result = await self.orchestrator.run_on_host(
                    host=host,
                    task=task,
                    skill=skill,
                    # timeout is now determined by orchestrator based on skill config
                )
                return HostResult(
                    host=host,
                    success=result.success,
                    output=result.output,
                    error=result.error,
                    duration_ms=result.duration_ms,
                    tool_calls=result.tool_calls,
                )
            else:
                # Fallback to simulation mode (for testing)
                output = await self._simulate_execution(skill, host, task)
                tool_calls = 1

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            return HostResult(
                host=host,
                success=True,
                output=output,
                duration_ms=duration_ms,
                tool_calls=tool_calls,
            )

        except TimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            # Timeout message now includes reason (idle vs max)
            timeout_msg = str(e) if str(e) else "unknown timeout"
            logger.warning(f"⏱️ Timeout on host '{host}': {timeout_msg}")
            return HostResult(
                host=host,
                success=False,
                error=f"Timeout: {timeout_msg}",
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
        Simulate skill execution (fallback for testing).

        Used when no SharedContext is provided (e.g., in unit tests).

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
            completed_at=datetime.now(UTC),
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
            return bool(await confirm_callback(f"Confirm {operation}?"))

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
