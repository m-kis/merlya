"""
Merlya SSH - Command executor.

Handles SSH command execution.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from merlya.ssh.pty_handler import execute_with_pty, needs_pty_for_command
from merlya.ssh.types import (
    SSHConnection,
    SSHConnectionOptions,
    SSHResult,
)

if TYPE_CHECKING:
    from asyncssh import SSHCompletedProcess


@dataclass
class ExecuteParams:
    """Parameters for SSH command execution.

    Groups parameters to respect the 4-parameter limit from CONTRIBUTING.md.

    Note: Connection credentials (username, private_key) are managed
    separately by the connection pool and passed during connection creation.
    """

    host: str
    command: str
    timeout: int = 60
    input_data: str | None = None
    options: SSHConnectionOptions | None = None
    host_name: str | None = None  # Inventory name for credential lookup


async def execute_command(
    params: ExecuteParams,
    conn: SSHConnection,
    very_verbose_debug: bool = False,
) -> SSHResult:
    """Execute a command on an SSH connection.

    Args:
        params: Execution parameters.
        conn: Active SSH connection.
        very_verbose_debug: Enable verbose debug logging.

    Returns:
        SSHResult with stdout, stderr, and exit_code.

    Raises:
        RuntimeError: If connection is closed.
        TimeoutError: If command times out.
        asyncio.CancelledError: If execution is cancelled.
    """
    if conn.connection is None:
        raise RuntimeError(f"Connection to {params.host} is closed")

    try:
        # Check if PTY is needed
        if needs_pty_for_command(params.command, params.input_data is not None):
            # Allow input_data to be None by using empty string as default
            input_data = params.input_data if params.input_data is not None else ""
            result = await execute_with_pty(
                conn,
                params.command,
                input_data,
                params.timeout,
                very_verbose_debug,
            )
            logger.debug(
                f"⚡ Executed command on {params.host} (PTY, length: {len(params.command)} chars, "
                f"exit: {result.exit_code})"
            )
            return result

        # Standard execution (no PTY)
        completed: SSHCompletedProcess
        if params.input_data is not None:
            completed = await asyncio.wait_for(
                conn.connection.run(params.command, input=params.input_data),
                timeout=params.timeout,
            )
        else:
            completed = await asyncio.wait_for(
                conn.connection.run(params.command),
                timeout=params.timeout,
            )

        # Security: Never log command content (may contain secrets)
        logger.debug(
            f"⚡ Executed command on {params.host} (length: {len(params.command)} chars, "
            f"exit: {completed.exit_status})"
        )

        # Ensure strings (asyncssh may return bytes)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        return SSHResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=completed.exit_status or 0,
        )

    except TimeoutError:
        logger.warning(f"⚠️ Command timeout on {params.host}")
        raise
    except asyncio.CancelledError:
        # Handle Ctrl+C - propagate for REPL to handle
        logger.debug(f"🛑 SSH execution cancelled on {params.host}")
        raise
