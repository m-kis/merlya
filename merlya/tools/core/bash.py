"""
Merlya Tools - Local bash execution.

Execute commands locally on the Merlya host machine.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.resolve import resolve_all_references
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

    # Resolve all @references FIRST (hosts then secrets)
    # This must happen before security check to catch dangerous patterns in references
    try:
        resolved_command, safe_command = await resolve_all_references(command, ctx)
    except Exception as e:
        # Use a truncated version of the command for logging to avoid potential secret leaks
        safe_display = command[:50] + "..." if len(command) > 50 else command
        logger.error(f"❌ Reference resolution failed for command: {safe_display}")
        return ToolResult(
            success=False,
            data={"command": command[:50]},  # Safe: original command before resolution
            error=f"Reference resolution failed: {e}",
        )

    try:
        # SECURITY: Check for dangerous commands AFTER reference resolution
        # This catches dangerous patterns hidden in @host or @secret references
        if is_dangerous_command(resolved_command):
            return ToolResult(
                success=False,
                error="⚠️ SECURITY: Command blocked - potentially destructive",
                data={"command": safe_command[:50]},  # Use safe_command, not resolved
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
            # Drain streams and ensure process is reaped to avoid zombies
            await process.communicate()
            logger.warning(f"⏱️ Command timed out after {timeout}s")
            return ToolResult(
                success=False,
                error=f"⏱️ Command timed out after {timeout}s",
                data={"command": safe_command[:50], "timeout": timeout},
            )

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        # returncode should always be set after communicate(), but handle None explicitly
        exit_code = process.returncode if process.returncode is not None else -1

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
        # Use safe_command when available to avoid leaking secrets, fall back to command
        display_command = safe_command[:50] if safe_command else command[:50]
        logger.error(f"❌ Local execution failed: {e}")
        return ToolResult(
            success=False,
            data={"command": display_command},  # Use safe_command to avoid secret leak
            error=str(e),
        )
