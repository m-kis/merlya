"""
Specialist delegation tools for the orchestrator.

Contains @agent.tool decorated functions for delegating to specialists.
"""

from __future__ import annotations

from loguru import logger
from pydantic_ai import Agent, RunContext  # noqa: TC002 - required at runtime

from .models import DelegationResult, OrchestratorDeps, OrchestratorResponse  # noqa: TC001
from .specialist_runner import run_specialist_once, run_specialist_with_retry
from .target_normalization import normalize_target


def register_specialist_tools(
    agent: Agent[OrchestratorDeps, OrchestratorResponse],
) -> None:
    """Register specialist delegation tools."""

    @agent.tool
    async def delegate_diagnostic(
        ctx: RunContext[OrchestratorDeps],
        target: str,
        task: str,
    ) -> DelegationResult:
        """
        Delegate diagnostic task to the Diagnostic specialist.

        Use for: Investigation, read-only checks, log analysis, performance diagnosis.
        The specialist has: ssh_execute (read-only), bash (read-only), read_file, scan.

        Args:
            target: Target host or "local" for local commands.
            task: Clear description of what to investigate.

        Returns:
            DelegationResult with findings.
        """
        from merlya.agent.specialists import run_diagnostic_agent

        # ENFORCE LOCAL: If task doesn't mention a specific host, use local
        effective_target = await normalize_target(target, task, ctx.deps.context)
        logger.info(f"Delegating diagnostic to {effective_target}: {task[:50]}...")

        result = await run_specialist_with_retry(
            ctx=ctx,
            specialist_fn=run_diagnostic_agent,
            specialist_type="diagnostic",
            target=effective_target,
            task=task,
        )

        return result

    @agent.tool
    async def delegate_execution(
        ctx: RunContext[OrchestratorDeps],
        target: str,
        task: str,
        require_confirmation: bool = True,
    ) -> DelegationResult:
        """
        Delegate execution task to the Execution specialist.

        Use for: Actions that modify state - restart services, edit configs, deploy.
        The specialist has: ssh_execute, bash, write_file, request_credentials.

        Args:
            target: Target host or "local" for local commands.
            task: Clear description of what action to perform.
            require_confirmation: If True, user confirms before destructive actions.

        Returns:
            DelegationResult with action outcome.
        """
        from merlya.agent.specialists import run_execution_agent

        # ENFORCE LOCAL: If task doesn't mention a specific host, use local
        effective_target = await normalize_target(target, task, ctx.deps.context)
        logger.info(f"Delegating execution to {effective_target}: {task[:50]}...")

        result = await run_specialist_with_retry(
            ctx=ctx,
            specialist_fn=run_execution_agent,
            specialist_type="execution",
            target=effective_target,
            task=task,
            require_confirmation=require_confirmation,
        )

        return result

    @agent.tool
    async def delegate_security(
        ctx: RunContext[OrchestratorDeps],
        target: str,
        task: str,
    ) -> DelegationResult:
        """
        Delegate security task to the Security specialist.

        Use for: Security scans, vulnerability analysis, compliance checks.
        The specialist has: ssh_execute, bash, scan, security_* tools.

        Args:
            target: Target host or "all" for full scan.
            task: Clear description of security check to perform.

        Returns:
            DelegationResult with security findings.
        """
        from merlya.agent.specialists import run_security_agent

        logger.info(f"Delegating security to {target}: {task[:50]}...")

        # Security tasks are NOT relaunched (sensitive operations)
        result = await run_specialist_once(
            ctx=ctx,
            specialist_fn=run_security_agent,
            specialist_type="security",
            target=target,
            task=task,
        )

        return result

    @agent.tool
    async def delegate_query(
        ctx: RunContext[OrchestratorDeps],
        question: str,
    ) -> DelegationResult:
        """
        Delegate simple query to the Query specialist.

        Use for: Quick questions about hosts, inventory, status.
        The specialist has: list_hosts, get_host, ask_user (NO ssh_execute).

        Args:
            question: Question about inventory or system status.

        Returns:
            DelegationResult with answer.
        """
        from merlya.agent.specialists import run_query_agent

        logger.info(f"Delegating query: {question[:50]}...")

        # Query tasks are fast and NOT relaunched
        result = await run_specialist_once(
            ctx=ctx,
            specialist_fn=run_query_agent,
            specialist_type="query",
            target="local",
            task=question,
        )

        return result
