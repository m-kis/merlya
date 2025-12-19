"""
Merlya Agent Specialists - Security agent.

Security scans and compliance (25 tool calls max).
"""

from __future__ import annotations

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.elevation import (
    auto_collect_elevation_credentials,
    needs_elevation_stdin,
)
from merlya.agent.specialists.prompts import SECURITY_PROMPT
from merlya.agent.specialists.types import ScanResult, SSHResult
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
    """Register security tools."""

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[SpecialistDeps],
        host: str,
        command: str,
        timeout: int = 60,
        stdin: str | None = None,
    ) -> SSHResult:
        """Execute a security command on a remote host."""
        from merlya.tools.core import ssh_execute as _ssh_execute

        # AUTO-ELEVATION: Collect credentials if needed
        effective_stdin = stdin
        if needs_elevation_stdin(command) and not stdin:
            logger.debug(f"🔐 Auto-elevation: {command[:40]}...")
            effective_stdin = await auto_collect_elevation_credentials(
                ctx.deps.context, host, command
            )
            if not effective_stdin:
                return SSHResult(
                    success=False,
                    stdout="",
                    stderr="Credentials required but not provided",
                    exit_code=-1,
                    error="User cancelled credential prompt",
                )

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command.")

        ctx.deps.tracker.record(host, command)

        result = await _ssh_execute(ctx.deps.context, host, command, timeout, stdin=effective_stdin)

        return SSHResult(
            success=result.success,
            stdout=result.data.get("stdout", "") if result.data else "",
            stderr=result.data.get("stderr", "") if result.data else "",
            exit_code=result.data.get("exit_code", -1) if result.data else -1,
        )

    @agent.tool
    async def bash(
        ctx: RunContext[SpecialistDeps],
        command: str,
        timeout: int = 60,
    ) -> SSHResult:
        """Execute a local security command."""
        from merlya.tools.core import bash_execute as _bash_execute

        would_loop, reason = ctx.deps.tracker.would_loop("local", command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command.")

        ctx.deps.tracker.record("local", command)

        result = await _bash_execute(ctx.deps.context, command, timeout)
        return SSHResult(
            success=result.success,
            stdout=result.data.get("stdout", "") if result.data else "",
            stderr=result.data.get("stderr", "") if result.data else "",
            exit_code=result.data.get("exit_code", -1) if result.data else -1,
        )

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
