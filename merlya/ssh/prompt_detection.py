"""
Merlya SSH - Password prompt detection.

Detects password prompts in SSH output for sudo/su/doas commands.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from asyncssh.process import SSHClientProcess


# Password prompt patterns for sudo/su/doas detection
# These are matched case-insensitively against stdout
PASSWORD_PROMPT_PATTERNS = (
    "password:",
    "[sudo]",
    "mot de passe",  # French
    "contraseña",  # Spanish
    "passwort",  # German
    "password for",
    "authenticate:",
)

# Pre-compiled regex for sanitization (CONTRIBUTING guidelines)
_SANITIZE_PATTERN = re.compile(r"[a-zA-Z0-9]")


def sanitize_for_logging(text: str) -> str:
    """Sanitize text for safe logging by masking alphanumeric characters.

    Replaces all alphanumeric characters with bullet to prevent leaking
    sensitive data like passwords, while preserving structure for debugging.

    Args:
        text: Text to sanitize.

    Returns:
        Sanitized text with alphanumeric characters masked.
    """
    return _SANITIZE_PATTERN.sub("•", text)


async def wait_for_prompt(
    process: SSHClientProcess[str],
    patterns: tuple[str, ...] = PASSWORD_PROMPT_PATTERNS,
    timeout: float = 5.0,
    very_verbose: bool = False,
) -> tuple[bool, str]:
    """Wait for password prompt to appear in stdout.

    Reads stdout incrementally until a password prompt pattern is detected
    or timeout is reached. This replaces the unreliable fixed sleep.

    Args:
        process: SSH process with stdout.
        patterns: Tuple of patterns to match (case-insensitive).
        timeout: Maximum time to wait for prompt.
        very_verbose: If True, include sanitized buffer content in logs.

    Returns:
        Tuple of (prompt_found, buffer_content).
    """
    buffer = ""
    start = time.monotonic()

    while time.monotonic() - start < timeout:
        try:
            # Read with short timeout to allow cancellation
            if process.stdout:
                chunk = await asyncio.wait_for(
                    process.stdout.read(1024),
                    timeout=0.3,
                )
                if chunk:
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode("utf-8", errors="replace")
                    buffer += chunk

                    # Check if any prompt pattern matches
                    buffer_lower = buffer.lower()
                    if any(p in buffer_lower for p in patterns):
                        if very_verbose:
                            sanitized = sanitize_for_logging(buffer[-50:])
                            logger.debug(f"🔑 Password prompt detected (sanitized): {sanitized!r}")
                        else:
                            logger.debug("🔑 Password prompt detected")
                        return True, buffer
            else:
                # No stdout available, can't detect prompt
                break
        except TimeoutError:
            # Read timeout, continue waiting
            continue
        except asyncio.CancelledError:
            # Propagate cancellation
            raise

    if very_verbose:
        sanitized = sanitize_for_logging(buffer[-100:])
        logger.debug(f"⚠️ No prompt detected after {timeout}s (sanitized): {sanitized!r}")
    else:
        logger.debug(f"⚠️ No prompt detected after {timeout}s (buffer length: {len(buffer)} chars)")
    return False, buffer
