"""
Merlya Agent Specialists - Diagnostic agent.

Read-only investigation agent (40 tool calls max).
"""

from __future__ import annotations

import shlex

from loguru import logger
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.usage import UsageLimits

from merlya.agent.specialists.deps import SpecialistDeps
from merlya.agent.specialists.elevation import (
    auto_collect_elevation_credentials,
    needs_elevation_stdin,
)
from merlya.agent.specialists.prompts import DIAGNOSTIC_PROMPT
from merlya.agent.specialists.types import FileReadResult, SSHResult
from merlya.config.providers import get_model_for_role, get_pydantic_model_string


async def run_diagnostic_agent(
    deps: SpecialistDeps,
    task: str,
    usage_limits: UsageLimits | None = None,
) -> str:
    """
    Run the Diagnostic agent.

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
        system_prompt=DIAGNOSTIC_PROMPT,
        defer_model_check=True,
        retries=3,
    )

    _register_tools(agent)

    limits = usage_limits or UsageLimits(tool_calls_limit=40)
    prompt = f"Target: {deps.target}\n\nTask: {task}"

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=limits)
        return str(result.output)
    except Exception as e:
        logger.error(f"❌ Diagnostic agent error: {e}", exc_info=True)
        return "❌ The investigation encountered an error. Check the logs."


def _register_tools(agent: Agent[SpecialistDeps, str]) -> None:
    """Register diagnostic tools (read-only)."""

    @agent.tool
    async def ssh_execute(
        ctx: RunContext[SpecialistDeps],
        host: str,
        command: str,
        timeout: int = 60,
        stdin: str | None = None,
    ) -> SSHResult:
        """Execute a command on a remote host via SSH (read-only)."""
        from merlya.tools.core import bash_execute as _bash_execute
        from merlya.tools.core import ssh_execute as _ssh_execute

        # ENFORCE TARGET: When target is "local", use bash regardless of host parameter
        target = ctx.deps.target.lower() if ctx.deps.target else ""
        if target in ("local", "localhost", "127.0.0.1", "::1"):
            # Redirect to bash for local targets
            logger.info(f"🖥️ Target is local, executing locally: {command[:50]}...")

            # Check for loop BEFORE recording
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
                hint=str(result.data.get("hint", ""))
                if result.data and result.data.get("hint")
                else None,
                error=result.error if result.error else None,
            )

        # For remote targets, use actual SSH
        effective_host = host

        # AUTO-ELEVATION: Collect credentials if needed
        effective_stdin = stdin
        if needs_elevation_stdin(command) and not stdin:
            logger.debug(f"🔐 Auto-elevation: {command[:40]}...")
            effective_stdin = await auto_collect_elevation_credentials(
                ctx.deps.context, effective_host, command
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
        would_loop, reason = ctx.deps.tracker.would_loop(effective_host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command.")

        ctx.deps.tracker.record(effective_host, command)

        result = await _ssh_execute(
            ctx.deps.context, effective_host, command, timeout, stdin=effective_stdin
        )

        return SSHResult(
            success=result.success,
            stdout=result.data.get("stdout", "") if result.data else "",
            stderr=result.data.get("stderr", "") if result.data else "",
            exit_code=result.data.get("exit_code", -1) if result.data else -1,
            hint=str(result.data.get("hint", ""))
            if result.data and result.data.get("hint")
            else None,
            error=result.error if result.error else None,
        )

    @agent.tool
    async def bash(
        ctx: RunContext[SpecialistDeps],
        command: str,
        timeout: int = 60,
    ) -> SSHResult:
        """Execute a local command (kubectl, docker, aws, etc.)."""
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
            hint=str(result.data.get("hint", ""))
            if result.data and result.data.get("hint")
            else None,
            error=result.error if result.error else None,
        )

    @agent.tool
    async def read_file(
        ctx: RunContext[SpecialistDeps],
        host: str,
        path: str,
    ) -> FileReadResult:
        """Read a file from a remote host."""
        from merlya.tools.core import ssh_execute as _ssh_execute

        quoted_path = shlex.quote(path)
        command = f"cat -- {quoted_path}"

        # Check for loop BEFORE recording
        would_loop, reason = ctx.deps.tracker.would_loop(host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT approach.")

        ctx.deps.tracker.record(host, command)

        result = await _ssh_execute(ctx.deps.context, host, command, timeout=30)
        return FileReadResult(
            success=result.success,
            content=result.data.get("stdout", "") if result.data else "",
            error=result.data.get("stderr", "") if result.data else "",
        )
