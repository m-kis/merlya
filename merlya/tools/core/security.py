"""
Merlya Tools - Security checks.

Detects unsafe patterns in commands to prevent credential leaks.
"""

from __future__ import annotations

import re

from loguru import logger

# =============================================================================
# PASSWORD DETECTION PATTERNS
# =============================================================================

# Patterns that likely contain plaintext passwords (security risk)
# These patterns detect when a password is embedded directly instead of using @secret-name references
UNSAFE_PASSWORD_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Pattern 1: echo password | sudo -S
    # Matches: echo 'password' | sudo -S, echo password | sudo -S
    # Skips: echo '@secret' | sudo -S
    re.compile(r"echo\s+['\"]?(?!@)[^'\"]+['\"]?\s*\|\s*sudo\s+-S", re.IGNORECASE),
    # Pattern 2: mysql -p'password' (with quotes)
    # Matches: -p'password', -p"password"
    # Skips: -p'@secret', -print, -pine64 (bare -p without quotes)
    re.compile(r"-p['\"][^'\"@]+['\"]", re.IGNORECASE),
    # Pattern 3: --password=value
    # Matches: --password=secret, --password 'secret'
    # Skips: --password=@secret
    re.compile(r"--password[=\s]+['\"]?(?!@)[^@\s'\"]+['\"]?", re.IGNORECASE),
    # Pattern 4: Environment variable setting
    # Matches: MYSQL_PWD=secret, PASSWORD=foo, export PASSWD=bar
    # Skips: MYSQL_PWD=@secret
    re.compile(
        r"(?:export\s+)?(?:MYSQL_PWD|PASSWORD|PASSWD|DB_PASSWORD|API_KEY|SECRET_KEY)"
        r"=['\"]?(?!@)[^@\s'\"]+['\"]?",
        re.IGNORECASE,
    ),
    # Pattern 5: curl -u user:password
    # Matches: -u user:password, -u 'user:pass'
    # Skips: -u user:@secret
    re.compile(r"-u\s+['\"]?\w+:(?!@)[^@\s'\"]+['\"]?", re.IGNORECASE),
    # Pattern 6: sshpass -p password
    # Matches: sshpass -p 'password', sshpass -p password
    # Skips: sshpass -p '@secret'
    re.compile(r"sshpass\s+-p\s+['\"]?(?!@)[^'\"@\s]+['\"]?", re.IGNORECASE),
    # Pattern 7: Connection strings with passwords
    # Matches: postgresql://user:pass@host, mysql://user:pass@host
    # Skips: postgresql://user:@secret@host
    re.compile(r"://[\w]+:(?!@)[^@\s'\"]+@", re.IGNORECASE),
    # Pattern 8: Variable assignment in shell
    # Matches: pass=secret, password="foo", PASSWD='bar'
    # Skips: pass=@secret
    re.compile(
        r"\b(?:pass|password|passwd|secret|token|api_key)\s*=\s*['\"]?(?!@)[^'\"@\s;]+['\"]?",
        re.IGNORECASE,
    ),
)


def detect_unsafe_password(command: str) -> str | None:
    """
    Detect if a command contains a potential plaintext password.

    Args:
        command: Command string to check.

    Returns:
        Warning message if unsafe pattern detected, None otherwise.
        Commands using @secret-name references are considered safe.

    Examples:
        >>> detect_unsafe_password("echo 'mypass' | sudo -S")
        '... SECURITY: Command may contain a plaintext password...'
        >>> detect_unsafe_password("echo '@sudo:host:password' | sudo -S")
        None
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


# =============================================================================
# DANGEROUS COMMAND DETECTION
# =============================================================================

# Regex patterns for dangerous commands (more robust than string matching)
# Normalizes whitespace and handles variations like 'rm -fr' vs 'rm -rf'
DANGEROUS_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    # rm -rf / or rm -rf /* (handles rm -rf, rm -fr, rm --recursive --force)
    re.compile(r"\brm\s+(-[rf]+\s*)+/+\*?\s*$", re.IGNORECASE),
    re.compile(r"\brm\s+--recursive\s+--force\s+/", re.IGNORECASE),
    # mkfs (any filesystem format command)
    re.compile(r"\bmkfs[.\s]", re.IGNORECASE),
    # dd to disk devices
    re.compile(r"\bdd\s+.*(?:of|if)=/dev/(?:sd|hd|vd|nvme|xvd)", re.IGNORECASE),
    # Fork bomb
    re.compile(r":\s*\(\s*\)\s*\{.*:\s*\|\s*:.*&.*\}\s*;\s*:", re.IGNORECASE),
    # Redirect to disk devices
    re.compile(r">\s*/dev/(?:sd|hd|vd|nvme|xvd)", re.IGNORECASE),
    # chmod 777 on root
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/+\s*$", re.IGNORECASE),
    # wipefs (wipes filesystem signatures)
    re.compile(r"\bwipefs\s+", re.IGNORECASE),
    # shred on devices
    re.compile(r"\bshred\s+.*--?(?:z|zero)", re.IGNORECASE),
)

# Simple string patterns for exact matches (legacy, for backwards compat)
DANGEROUS_COMMANDS: frozenset[str] = frozenset(
    {
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero",
        ":(){ :|:& };:",
        "> /dev/sda",
        "chmod -R 777 /",
    }
)


def is_dangerous_command(command: str) -> bool:
    """
    Check if a command is potentially destructive.

    Uses both regex patterns (for robust matching) and string patterns
    (for exact matches).

    Args:
        command: Command string to check.

    Returns:
        True if command matches a dangerous pattern.

    Examples:
        >>> is_dangerous_command("rm -rf /")
        True
        >>> is_dangerous_command("rm  -rf  /")  # Extra spaces
        True
        >>> is_dangerous_command("rm -rf /tmp/test")
        False
    """
    # Normalize whitespace for consistent matching
    cmd_normalized = " ".join(command.split()).lower()

    # Check regex patterns first (more robust)
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(cmd_normalized):
            logger.warning(f"🔒 Blocked dangerous command (pattern): {command[:50]}")
            return True

    # Check exact string matches
    for dangerous in DANGEROUS_COMMANDS:
        if dangerous in cmd_normalized:
            logger.warning(f"🔒 Blocked dangerous command (exact): {command[:50]}")
            return True

    return False
