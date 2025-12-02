"""
SSH channel utilities with timeout protection.

Provides safe channel reading that prevents blocking on Broken Pipe errors
and other connection issues. Used by both SSHManager and on-demand scanner.
"""
import select
import socket
import time
from typing import Optional, Tuple

import paramiko

from merlya.utils.logger import logger

# Poll interval for select() - check exit_status_ready() regularly
_SELECT_POLL_INTERVAL = 1.0


def read_channel_with_timeout(
    channel: paramiko.Channel,
    timeout: float = 60.0,
    max_bytes: int = 65536,
) -> Tuple[str, str, int]:
    """
    Read from Paramiko channel with proper timeout protection.

    Paramiko's stdout.read() can block indefinitely on Broken Pipe errors.
    This function uses select() to implement a real timeout.

    Args:
        channel: Paramiko channel from exec_command() or open_session()
        timeout: Maximum time to wait for output (seconds)
        max_bytes: Maximum bytes to read per chunk

    Returns:
        Tuple of (stdout, stderr, exit_status)
        exit_status is -1 if not available
    """
    stdout_data: list[bytes] = []
    stderr_data: list[bytes] = []
    exit_status = -1

    # Set channel to non-blocking mode for select() to work
    channel.setblocking(0)

    start_time = time.monotonic()
    remaining = timeout

    try:
        while remaining > 0:
            # Use select to wait for data with timeout
            readable, _, _ = select.select(
                [channel], [], [], min(remaining, _SELECT_POLL_INTERVAL)
            )

            if not readable:
                # Check if channel is closed/finished
                if channel.exit_status_ready():
                    break
                # Update remaining time
                elapsed = time.monotonic() - start_time
                remaining = timeout - elapsed
                continue

            # Read available data - check recv_ready() first to avoid race condition
            if channel.recv_ready():
                chunk = channel.recv(max_bytes)
                if chunk:
                    stdout_data.append(chunk)
                else:
                    # Empty chunk means EOF
                    break

            if channel.recv_stderr_ready():
                chunk = channel.recv_stderr(max_bytes)
                if chunk:
                    stderr_data.append(chunk)

            # Check if command finished and all data consumed
            # Note: Minor TOCTOU race acceptable - next iteration catches late data
            if not channel.recv_ready() and channel.exit_status_ready():
                break

            # Update remaining time
            elapsed = time.monotonic() - start_time
            remaining = timeout - elapsed

        # Get exit status if available
        if channel.exit_status_ready():
            exit_status = channel.recv_exit_status()

        # Log timeout if we ran out of time
        if remaining <= 0:
            logger.warning(f"⏱️ Channel read timed out after {timeout}s")

    except (OSError, socket.error) as e:
        elapsed = time.monotonic() - start_time
        logger.debug(
            f"⚠️ Channel read network error: {type(e).__name__}: {e} "
            f"(timeout={timeout}s, elapsed={elapsed:.2f}s)"
        )
    except paramiko.SSHException as e:
        elapsed = time.monotonic() - start_time
        logger.debug(
            f"⚠️ Channel SSH protocol error: {e} "
            f"(timeout={timeout}s, elapsed={elapsed:.2f}s)"
        )
    except Exception as e:
        elapsed = time.monotonic() - start_time
        logger.debug(
            f"⚠️ Channel read error ({type(e).__name__}): {e} "
            f"(timeout={timeout}s, elapsed={elapsed:.2f}s)"
        )
    finally:
        try:
            channel.close()
        except Exception as e:
            logger.debug(f"⚠️ Channel close warning: {type(e).__name__}: {e}")

    stdout = b"".join(stdout_data).decode("utf-8", errors="replace").strip()
    stderr = b"".join(stderr_data).decode("utf-8", errors="replace").strip()

    return stdout, stderr, exit_status


def exec_command_with_timeout(
    client: paramiko.SSHClient,
    command: str,
    timeout: float = 60.0,
) -> str:
    """
    Execute SSH command with timeout protection.

    This is the safe alternative to client.exec_command() that prevents
    blocking on Broken Pipe or other channel errors.

    Note: This function only provides timeout protection.
    Commands are NOT validated or sanitized - caller is responsible for
    ensuring command safety when using user-controlled input.

    Args:
        client: Paramiko SSHClient with active connection
        command: Shell command to execute
        timeout: Maximum time to wait (seconds)

    Returns:
        Command stdout as string, or empty string on error
    """
    channel: Optional[paramiko.Channel] = None
    try:
        # Get channel directly for more control
        transport = client.get_transport()
        if not transport or not transport.is_active():
            # Safe: no channel created yet
            return ""

        channel = transport.open_session()
        channel.settimeout(timeout)
        channel.exec_command(command)

        # read_channel_with_timeout closes the channel in its finally block
        stdout, stderr, exit_status = read_channel_with_timeout(channel, timeout)
        channel = None  # Mark as handled to avoid double-close

        if exit_status != 0 and stderr:
            logger.debug(
                f"⚠️ Command '{command[:50]}...' exited {exit_status}: "
                f"{stderr[:100]}"
            )

        return stdout

    except Exception as e:
        logger.debug(f"⚠️ Command exec failed for '{command[:30]}...': {e}")
        # Close channel if created but read_channel_with_timeout wasn't called
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass
        return ""
