"""
Merlya SSH - PTY execution handler.

Handles command execution with pseudo-terminal (PTY) for sudo/su/doas.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from loguru import logger

from merlya.ssh.prompt_detection import (
    PASSWORD_PROMPT_PATTERNS,
    sanitize_for_logging,
    wait_for_prompt,
)
from merlya.ssh.types import SSHConnection, SSHResult

if TYPE_CHECKING:
    from asyncssh.process import SSHClientProcess


def has_sudo_password_indicators(buffer: str) -> bool:
    """Check if buffer contains explicit sudo-password indicators.

    This function examines the buffer for patterns that indicate
    a sudo password is being requested, even if the main prompt
    detection missed them.

    Args:
        buffer: The buffer content to examine.

    Returns:
        True if explicit password indicators are found, False otherwise.
    """
    if not buffer:
        return False

    buffer_lower = buffer.lower()

    # Check for explicit sudo password indicators
    sudo_password_indicators = [
        "password:",
        "[sudo]",
        "mot de passe",
        "contraseña",
        "passwort",
        "password for",
        "authenticate:",
        "enter password",
        "sudo password",
        "please enter password",
    ]

    return any(indicator in buffer_lower for indicator in sudo_password_indicators)


async def execute_with_pty(
    conn: SSHConnection,
    command: str,
    input_data: str,
    timeout: int,
    very_verbose_debug: bool = False,
) -> SSHResult:
    """Execute command with PTY and manual stdin input.

    For commands like su/sudo that need a PTY and password input,
    asyncssh's run() with input + term_type doesn't work reliably.
    We need to create a process and manually write to stdin.

    This function:
    1. Creates a PTY process
    2. Waits for the password prompt (instead of fixed sleep)
    3. Writes the password when prompt is detected
    4. Handles CancelledError for Ctrl+C support

    Args:
        conn: SSH connection wrapper.
        command: Command to execute.
        input_data: Password or stdin data to send.
        timeout: Command timeout in seconds.
        very_verbose_debug: Enable verbose debug logging.

    Returns:
        SSHResult with stdout, stderr, and exit_code.

    Raises:
        RuntimeError: If connection is closed.
        asyncio.CancelledError: If execution is cancelled (Ctrl+C).

    Note:
        When PTY is allocated, stderr is merged into stdout.
    """
    if conn.connection is None:
        raise RuntimeError("Connection is closed")

    process: SSHClientProcess[str] | None = None

    async def _run_with_pty() -> SSHResult:
        nonlocal process
        assert conn.connection is not None  # For type checker

        # Create process with PTY
        async with conn.connection.create_process(
            command,
            term_type="xterm",
            term_size=(80, 24),
        ) as proc:
            process = proc

            # Wait for password prompt instead of fixed sleep
            prompt_found, prompt_buffer = await wait_for_prompt(
                proc,
                PASSWORD_PROMPT_PATTERNS,
                timeout=5.0,
                very_verbose=very_verbose_debug,
            )

            # Smart password handling based on prompt detection and buffer analysis
            password_needed = False

            if prompt_found:
                # Main prompt detection found indicators - password definitely needed
                password_needed = True
                logger.debug("🔑 Main prompt detection confirmed - sending password")
            else:
                # No main prompt found - check buffer for explicit sudo-password indicators
                if has_sudo_password_indicators(prompt_buffer):
                    password_needed = True
                    logger.debug(
                        "🔑 Buffer analysis found sudo password indicators - sending password"
                    )
                    if very_verbose_debug:
                        sanitized_buffer = sanitize_for_logging(prompt_buffer[-100:])
                        logger.debug(f"Buffer content (sanitized): {sanitized_buffer!r}")
                else:
                    # No explicit password indicators found
                    # This could be:
                    # 1. Passwordless sudo (no password required)
                    # 2. Normal command output
                    # 3. Command completed before password could be entered
                    # 4. Error or unexpected output
                    logger.debug(
                        "🚫 No sudo password indicators detected - treating as passwordless sudo or normal command"
                    )

                    if very_verbose_debug:
                        sanitized_buffer = sanitize_for_logging(prompt_buffer[-100:])
                        logger.debug(f"Unexpected buffer content (sanitized): {sanitized_buffer!r}")

                    # Don't send password - treat as passwordless sudo or completed command
                    # Continue to collect output without sending password

            # Only send password if indicators are present
            if password_needed:
                # Write password followed by newline
                password_with_newline = input_data
                if not password_with_newline.endswith("\n"):
                    password_with_newline += "\n"

                proc.stdin.write(password_with_newline)

                # Close stdin to signal EOF (important for su/sudo when password was sent)
                proc.stdin.write_eof()
            # No password needed: either passwordless sudo or normal command
            # Let the process handle stdin naturally without explicit EOF

            # Collect remaining stdout (stderr is merged into stdout with PTY)
            stdout_bytes = b""
            if proc.stdout:
                stdout_bytes = await proc.stdout.read()

            # Wait for process to complete
            await proc.wait()

            # Decode bytes to string
            stdout_str = prompt_buffer  # Include the prompt we already read
            if stdout_bytes:
                if isinstance(stdout_bytes, bytes):
                    stdout_str += stdout_bytes.decode("utf-8", errors="replace")
                else:
                    stdout_str += str(stdout_bytes)

            return SSHResult(
                stdout=stdout_str,
                stderr="",  # Merged into stdout with PTY
                exit_code=proc.exit_status or 0,
            )

    try:
        return await asyncio.wait_for(_run_with_pty(), timeout=timeout)
    except asyncio.CancelledError:
        # Handle Ctrl+C - clean up the process properly
        logger.debug("🛑 SSH PTY execution cancelled")
        if process is not None:
            with contextlib.suppress(Exception):
                process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=2.0)
        raise  # Re-propagate for REPL to handle
    except TimeoutError:
        # Handle timeout - clean up the process properly
        logger.debug("⏰ SSH PTY execution timed out")
        if process is not None:
            with contextlib.suppress(Exception):
                process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=2.0)
        raise  # Re-propagate for caller to handle


def needs_pty_for_command(command: str, has_input: bool) -> bool:
    """Check if command needs PTY execution.

    PTY is needed for commands that read passwords from stdin.

    Args:
        command: Command to check.
        has_input: Whether stdin data will be provided.

    Returns:
        True if PTY execution is needed.
    """
    if not has_input:
        return False

    cmd_stripped = command.lstrip()
    # sudo -S also needs PTY on some systems with requiretty or PAM config
    return cmd_stripped.startswith(("su ", "su -", "doas ", "sudo -S"))
