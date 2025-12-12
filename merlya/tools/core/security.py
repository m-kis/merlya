"""
Merlya Tools - Security checks.

Detects unsafe patterns in commands to prevent credential leaks.
"""

from __future__ import annotations

import re

from loguru import logger

# Patterns that likely contain plaintext passwords (security risk)
# These patterns detect when a password is embedded directly instead of using @secret-name references
UNSAFE_PASSWORD_PATTERNS: tuple[re.Pattern[str], ...] = (
    # echo 'pass' | sudo -S (but not echo '@secret' | sudo -S)
    re.compile(r"echo\s+['\"]?(?!@)[^'\"]+['\"]?\s*\|\s*sudo\s+-S", re.IGNORECASE),
    # -p'password' or -p"password" with QUOTES only (not bare -pX which could be flags like -print)
    # This avoids false positives on -pine64, -print-config, -path, etc.
    re.compile(r"-p['\"][^'\"@]+['\"]", re.IGNORECASE),
    # --password=pass (but not --password=@secret)
    re.compile(r"--password[=\s]+['\"]?(?!@)[^@\s'\"]+['\"]?", re.IGNORECASE),
    # MYSQL_PWD= or PASSWORD= environment variable setting
    re.compile(r"(?:MYSQL_PWD|PASSWORD|PASSWD)=['\"]?[^@\s'\"]+['\"]?", re.IGNORECASE),
    # curl -u user:password (but not curl -u user:@secret)
    re.compile(r"-u\s+['\"]?\w+:(?!@)[^@\s'\"]+['\"]?", re.IGNORECASE),
)


def detect_unsafe_password(command: str) -> str | None:
    """
    Detect if a command contains a potential plaintext password.

    Args:
        command: Command string to check.

    Returns:
        Warning message if unsafe pattern detected, None otherwise.
        Commands using @secret-name references are considered safe.
    """
    for i, pattern in enumerate(UNSAFE_PASSWORD_PATTERNS):
        match = pattern.search(command)
        if match:
            logger.warning(
                f"🔒 Password pattern {i} matched in command: '{command[:50]}...' at '{match.group()}'"
            )
            return (
                "⚠️ SECURITY: Command may contain a plaintext password. "
                "Use @secret-name references instead (e.g., @sudo:host:password)."
            )
    return None


# Dangerous commands that should be blocked for safety
DANGEROUS_COMMANDS: frozenset[str] = frozenset(
    {
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero",
        ":(){ :|:& };:",  # Fork bomb
        "> /dev/sda",
        "chmod -R 777 /",
        "chown -R",  # Recursive ownership change on root
    }
)


def is_dangerous_command(command: str) -> bool:
    """
    Check if a command is potentially destructive.

    Args:
        command: Command string to check.

    Returns:
        True if command matches a dangerous pattern.
    """
    cmd_lower = command.lower().strip()
    for dangerous in DANGEROUS_COMMANDS:
        if dangerous in cmd_lower:
            logger.warning(f"🔒 Blocked dangerous command: {command[:50]}")
            return True
    return False
