"""
Center delegation tools for the orchestrator.

Contains @agent.tool decorated functions for delegating to centers.
"""

from __future__ import annotations

from loguru import logger
from pydantic_ai import Agent, RunContext  # noqa: TC002 - required at runtime

from .center_integration import convert_center_result, ensure_centers_registered
from .models import DelegationResult, OrchestratorDeps, OrchestratorResponse


def register_center_tools(
    agent: Agent[OrchestratorDeps, OrchestratorResponse],
) -> None:
    """Register center delegation tools."""

    @agent.tool
    async def delegate_diagnostic_center(
        ctx: RunContext[OrchestratorDeps],
        target: str,
        task: str,
    ) -> DelegationResult:
        """
        Delegate to DIAGNOSTIC center for read-only investigation.

        The DiagnosticCenter is specialized for safe, read-only operations:
        - System checks (disk, memory, CPU, processes)
        - Log analysis
        - Service status verification
        - Kubernetes read operations (kubectl get, describe, logs)
        - File reading

        Use this for any investigation that does NOT modify state.

        Args:
            target: Target host name or "local" for local operations.
            task: Clear description of what to investigate.

        Returns:
            DelegationResult with findings and evidence.
        """
        from merlya.centers.base import CenterDeps, CenterMode
        from merlya.centers.registry import CenterRegistry

        logger.info(f"Delegating to DiagnosticCenter for {target}: {task[:50]}...")

        try:
            registry = CenterRegistry.get_instance()
            ensure_centers_registered(registry, ctx.deps.context)
            center = registry.get(CenterMode.DIAGNOSTIC)
            deps = CenterDeps(target=target, task=task)
            result = await center.execute(deps)
            return convert_center_result(result, "diagnostic_center")
        except Exception as e:
            logger.error(f"DiagnosticCenter execution failed: {e}")
            return DelegationResult(
                success=False,
                output=f"DiagnosticCenter error: {e}",
                specialist="diagnostic_center",
                complete=False,
            )

    @agent.tool
    async def delegate_change_center(
        ctx: RunContext[OrchestratorDeps],
        target: str,
        task: str,
    ) -> DelegationResult:
        """
        Delegate to CHANGE center for controlled mutations.

        The ChangeCenter handles all state-modifying operations via Pipelines:
        - Service management (restart, stop, start)
        - Configuration changes
        - Package installation
        - Deployments (Ansible, Terraform, Kubernetes)

        ALL changes go through a Pipeline with HITL (Human-In-The-Loop) approval:
        Plan -> Diff/Preview -> Summary -> User Approval -> Apply -> Post-check -> Rollback if needed

        Use this for any operation that modifies state.

        Args:
            target: Target host name or "local" for local operations.
            task: Clear description of what change to perform.

        Returns:
            DelegationResult with operation outcome.
        """
        from merlya.centers.base import CenterDeps, CenterMode
        from merlya.centers.registry import CenterRegistry

        logger.info(f"Delegating to ChangeCenter for {target}: {task[:50]}...")

        try:
            registry = CenterRegistry.get_instance()
            ensure_centers_registered(registry, ctx.deps.context)
            center = registry.get(CenterMode.CHANGE)
            deps = CenterDeps(target=target, task=task)
            result = await center.execute(deps)
            return convert_center_result(result, "change_center")
        except Exception as e:
            logger.error(f"ChangeCenter execution failed: {e}")
            return DelegationResult(
                success=False,
                output=f"ChangeCenter error: {e}",
                specialist="change_center",
                complete=False,
            )
