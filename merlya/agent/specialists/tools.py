"""
Merlya Agent Specialists - Tool factories.

Eliminates ~200 lines of duplication across DiagnosticAgent, ExecutionAgent, and SecurityAgent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic_ai import ModelRetry, RunContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.agent.specialists.deps import SpecialistDeps
    from merlya.agent.specialists.types import SSHResult


def create_ssh_tool(
    mode: Literal["read", "write", "security"],
    requires_confirmation: bool = False,
) -> Callable[..., Any]:
    """
    Factory for ssh_execute tool with mode-specific behavior.

    Eliminates ~200 lines of duplication across 3 agents.

    Args:
        mode: Agent mode - "read" (DiagnosticAgent), "write" (ExecutionAgent), "security" (SecurityAgent)
        requires_confirmation: Add HITL confirmation step before execution (ExecutionAgent only)

    Returns:
        Async function compatible with @agent.tool decorator
    """

    async def ssh_execute(
        ctx: RunContext[SpecialistDeps],
        host: str,
        command: str,
        timeout: int = 60,
        stdin: str | None = None,
    ) -> SSHResult:
        """Execute a command on a remote host via SSH."""
        from merlya.agent.confirmation import ConfirmationResult, confirm_command
        from merlya.agent.specialists.elevation import (
            auto_collect_elevation_credentials,
            needs_elevation_stdin,
        )
        from merlya.agent.specialists.types import SSHResult
        from merlya.tools.core import bash_execute as _bash_execute
        from merlya.tools.core import ssh_execute as _ssh_execute

        # ENFORCE TARGET: read/write modes support local redirect, security does NOT
        target = ctx.deps.target.lower() if ctx.deps.target else ""
        is_local_target = target in ("local", "localhost", "127.0.0.1", "::1")

        # Security agent: NO local redirect (direct SSH only)
        if mode == "security" and is_local_target:
            logger.warning("⚠️ Security mode requires SSH connection, not local execution")
            return SSHResult(
                success=False,
                stdout="",
                stderr="Security scans require SSH connection",
                exit_code=-1,
                error="Use bash() for local security commands",
            )

        # Read/Write modes: Support local redirect
        if mode in ("read", "write") and is_local_target:
            logger.info(f"🖥️ Target is local, executing locally: {command[:50]}...")

            # Check for loop BEFORE confirmation
            would_loop, reason = ctx.deps.tracker.would_loop("local", command)
            if would_loop:
                raise ModelRetry(f"{reason}. Try a DIFFERENT command.")

            # HITL confirmation for write mode
            if requires_confirmation and not ctx.deps.confirmation_state.should_skip(command):
                confirm_result = await confirm_command(
                    ui=ctx.deps.context.ui,
                    command=command,
                    target="local",
                    state=ctx.deps.confirmation_state,
                )
                if confirm_result == ConfirmationResult.CANCEL:
                    return SSHResult(
                        success=False,
                        stdout="",
                        stderr="Cancelled by user",
                        exit_code=-1,
                    )

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

        # Check for loop BEFORE confirmation
        would_loop, reason = ctx.deps.tracker.would_loop(effective_host, command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command.")

        # HITL confirmation for write mode
        if requires_confirmation and not ctx.deps.confirmation_state.should_skip(command):
            confirm_result = await confirm_command(
                ui=ctx.deps.context.ui,
                command=command,
                target=effective_host,
                state=ctx.deps.confirmation_state,
            )
            if confirm_result == ConfirmationResult.CANCEL:
                return SSHResult(
                    success=False,
                    stdout="",
                    stderr="Cancelled by user",
                    exit_code=-1,
                )

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

    # Set docstring based on mode
    if mode == "read":
        ssh_execute.__doc__ = "Execute a command on a remote host via SSH (read-only)."
    elif mode == "write":
        ssh_execute.__doc__ = "Execute a command on a remote host via SSH (with confirmation)."
    else:  # security
        ssh_execute.__doc__ = "Execute a security command on a remote host."

    return ssh_execute


def create_bash_tool(requires_confirmation: bool = False) -> Callable[..., Any]:
    """
    Factory for bash tool with optional HITL confirmation.

    Args:
        requires_confirmation: Add HITL confirmation step before execution

    Returns:
        Async function compatible with @agent.tool decorator
    """

    async def bash(
        ctx: RunContext[SpecialistDeps],
        command: str,
        timeout: int = 60,
    ) -> SSHResult:
        """Execute a local command."""
        from merlya.agent.confirmation import ConfirmationResult, confirm_command
        from merlya.agent.specialists.types import SSHResult
        from merlya.tools.core import bash_execute as _bash_execute

        # Check for loop BEFORE confirmation
        would_loop, reason = ctx.deps.tracker.would_loop("local", command)
        if would_loop:
            raise ModelRetry(f"{reason}. Try a DIFFERENT command.")

        # HITL confirmation if required
        if requires_confirmation and not ctx.deps.confirmation_state.should_skip(command):
            confirm_result = await confirm_command(
                ui=ctx.deps.context.ui,
                command=command,
                target="local",
                state=ctx.deps.confirmation_state,
            )
            if confirm_result == ConfirmationResult.CANCEL:
                return SSHResult(
                    success=False,
                    stdout="",
                    stderr="Cancelled by user",
                    exit_code=-1,
                )

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

    return bash
