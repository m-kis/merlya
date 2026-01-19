"""
Merlya Agent Specialists - Security agent.

Security scans and compliance (25 tool calls max).
"""

from __future__ import annotations

from loguru import logger
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.prompts import SECURITY_PROMPT
from merlya.agent.specialists.tools import create_bash_tool, create_ssh_tool
from merlya.agent.specialists.types import ScanResult
from merlya.config.providers import get_model_for_role, get_pydantic_model_string


async def run_security_agent(
    deps: SpecialistDeps,
    task: str,
    usage_limits: UsageLimits | None = None,
) -> str:
    """
    Run the Security agent.

    Args:
        deps: Specialist dependencies (context, tracker, etc.).
        task: Task description.
        usage_limits: Optional usage limits.

    Returns:
        Agent output as string.
    """
    provider = deps.context.config.model.provider
    model_id = get_model_for_role(provider, "reasoning")
    model_string = get_pydantic_model_string(provider, model_id)

    agent = Agent(
        model_string,
        deps_type=SpecialistDeps,
        system_prompt=SECURITY_PROMPT,
        defer_model_check=True,
        retries=3,
    )

    _register_tools(agent)

    limits = usage_limits or UsageLimits(tool_calls_limit=25)
    prompt = f"Target: {deps.target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Security agent error: {e}", exc_info=True)
        return deps.context.t("errors.security.audit_error")


def _register_tools(agent: Agent[SpecialistDeps, str]) -> None:
    """Register security tools using tool factories."""

    # Use tool factory for ssh_execute (security mode - NO local redirect)
    ssh_tool = create_ssh_tool(mode="security", requires_confirmation=False)
    agent.tool(ssh_tool, name="ssh_execute")

    # Use tool factory for bash (no confirmation for security scans)
    bash_tool = create_bash_tool(requires_confirmation=False)
    agent.tool(bash_tool, name="bash")

    @agent.tool
    async def scan_host(
        ctx: RunContext[SpecialistDeps],
        host: str,
        scan_type: str = "security",
    ) -> ScanResult:
        """Run a security scan on a host."""
        from merlya.commands.handlers.scan_format import ScanOptions
        from merlya.commands.handlers.system import _scan_hosts_parallel

        try:
            opts = ScanOptions(scan_type=scan_type)
            result = await _scan_hosts_parallel(
                ctx.deps.context,
                [host],
                opts,
            )
            return ScanResult(
                success=result.success,
                message=result.message or "",
                data=result.data or {},
            )
        except Exception as e:
            logger.error(f"❌ Scan error for {host}: {e}", exc_info=True)
            return ScanResult(success=False, error="Scan failed. Check logs.")
