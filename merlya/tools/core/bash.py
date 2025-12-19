"""
Merlya Tools - Local bash execution.

Execute commands locally on the Merlya host machine.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.resolve import resolve_all_references
from merlya.tools.core.security import is_dangerous_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Global registry of running subprocesses for signal handling
# Uses WeakSet to avoid memory leaks from completed processes
_running_processes: weakref.WeakSet[asyncio.subprocess.Process] = weakref.WeakSet()


def kill_all_subprocesses() -> int:
    """Kill all tracked subprocesses. Called by signal handler.

    Returns:
        Number of processes killed.
    """
    killed = 0
    for process in list(_running_processes):
        try:
            if process.returncode is None:  # Still running
                process.kill()
                killed += 1
                logger.debug(f"🛑 Killed subprocess PID {process.pid}")
        except (ProcessLookupError, OSError):
            # Process already terminated
            pass
    return killed


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

    # BLOCK: Detect SSH commands that should use ssh_execute instead
    cmd_lower = command.strip().lower()
    ssh_patterns = ["ssh ", "ssh\t", "sshpass "]
    if any(cmd_lower.startswith(p) for p in ssh_patterns) or " | ssh " in cmd_lower:
        return ToolResult(
            success=False,
            error=(
                "❌ WRONG TOOL: Use ssh_execute() for remote commands, not bash('ssh ...')!\n"
                "Example: ssh_execute(host='192.168.1.7', command='ls -la')\n"
                "For sudo: ssh_execute(host='192.168.1.7', command='sudo ls -la')\n"
                "For sudo with password: ssh_execute(host='...', command='sudo -S ...', stdin='@secret-sudo')"
            ),
            data={"command": command[:80]},
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

        # Register for signal-based cleanup
        _running_processes.add(process)

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            # Drain streams and ensure process is reaped to avoid zombies
            with contextlib.suppress(Exception):
                await process.communicate()
            logger.warning(f"⏱️ Command timed out after {timeout}s")
            return ToolResult(
                success=False,
                error=f"⏱️ Command timed out after {timeout}s",
                data={"command": safe_command[:50], "timeout": timeout},
            )
        except asyncio.CancelledError:
            # Handle Ctrl+C: kill subprocess and propagate cancellation
            process.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.communicate(), timeout=2.0)
            logger.debug("🛑 Command cancelled by user")
            raise
        finally:
            # Remove from registry (WeakSet handles this automatically, but be explicit)
            _running_processes.discard(process)

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
