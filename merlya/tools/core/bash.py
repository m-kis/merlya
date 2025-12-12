"""
Merlya Tools - Local bash execution.

Execute commands locally on the Merlya host machine.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.resolve import (
    get_resolved_host_names,
    resolve_host_references,
    resolve_secrets,
)
from merlya.tools.core.security import is_dangerous_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def bash_execute(
    ctx: SharedContext,
    command: str,
    timeout: int = 60,
) -> ToolResult:
    """
    Execute a command locally on the Merlya host machine.

    Use this for local operations like kubectl, aws, gcloud, az CLI commands.

    Args:
        ctx: Shared context.
        command: Command to execute locally.
        timeout: Command timeout in seconds (1-3600).

    Returns:
        ToolResult with command output.
    """
    # Validate timeout
    if timeout < 1 or timeout > 3600:
        return ToolResult(
            success=False,
            error="⚠️ Timeout must be between 1 and 3600 seconds",
            data={"timeout": timeout},
        )

    # Validate command is not empty
    if not command or not command.strip():
        return ToolResult(
            success=False,
            error="⚠️ Command cannot be empty",
            data={},
        )

    try:
        # Security: Check for dangerous commands
        if is_dangerous_command(command):
            return ToolResult(
                success=False,
                error="⚠️ SECURITY: Command blocked - potentially destructive",
                data={"command": command[:50]},
            )

        # Get hosts for reference resolution
        all_hosts = await ctx.hosts.get_all()

        # 1. Resolve @hostname references → actual hostnames/IPs
        # (inventory → DNS → user prompt)
        resolved_command = await resolve_host_references(command, all_hosts, ctx.ui)

        # Track which host names were resolved (to skip in secret resolution)
        resolved_host_names = get_resolved_host_names(all_hosts)

        # 2. Resolve @secret references → actual values
        resolved_command, safe_command = resolve_secrets(
            resolved_command, ctx.secrets, resolved_host_names
        )

        logger.debug(f"🖥️ Executing locally: {safe_command[:80]}...")

        # Execute command
        process = await asyncio.create_subprocess_shell(
            resolved_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            logger.warning(f"⏱️ Command timed out after {timeout}s")
            return ToolResult(
                success=False,
                error=f"⏱️ Command timed out after {timeout}s",
                data={"command": safe_command[:50], "timeout": timeout},
            )

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        exit_code = process.returncode or 0

        return ToolResult(
            success=exit_code == 0,
            data={
                "stdout": stdout_str,
                "stderr": stderr_str,
                "exit_code": exit_code,
                "command": safe_command[:50] + "..." if len(safe_command) > 50 else safe_command,
            },
            error=stderr_str if exit_code != 0 else None,
        )

    except Exception as e:
        logger.error(f"❌ Local execution failed: {e}")
        return ToolResult(
            success=False,
            data={"command": command[:50]},
            error=str(e),
        )
