"""
Merlya Tools - SSH error detection patterns.

Constants for detecting permission errors and authentication failures.
"""

from __future__ import annotations

import re
import shlex
import threading
from typing import Any, NamedTuple, Protocol


class SSHExecutor(Protocol):
    """Protocol for SSH command execution."""

    async def __call__(
        self,
        host: str,
        command: str,
        timeout: int,
    ) -> Any:
        """Execute command on host with timeout, returning result with exit_code."""
        ...


# Authentication failure indicators (sudo/su password failures)
# IMPORTANT: Patterns are checked with .lower() - keep all patterns lowercase
AUTH_ERROR_PATTERNS: tuple[str, ...] = (
    # === Universal patterns (locale-independent, from source code) ===
    # PAM module identifiers (never translated)
    "pam_authenticate failed",
    "pam_unix(",  # Matches pam_unix(sudo:auth), pam_unix(su:auth), etc.
    "pam_authenticate",
    # Polkit/DBus (never translated - from source code)
    "polkit-agent-helper-1",
    "org.freedesktop.policykit",
    "not authorized",
    "accessdenied",
    # sudo/su prefix patterns (command names, not translated)
    "sudo:",
    "su:",
    "doas:",
    # === English locale ===
    "authentication failure",
    "sorry",
    "incorrect password",
    "permission denied",
    "must be run from a terminal",
    "password attempts",
    "a password is required",
    "not in sudoers",
    "user is not in the sudoers file",
    "interactive authentication required",
    "authorization required",
    # === French locale ===
    "désolé",
    "mot de passe incorrect",
    "aucun mot de passe",
    "échec d'authentification",
    "authentification requise",
    "tentatives de mot de passe",
    # === German locale ===
    "falsches passwort",
    "authentifizierung fehlgeschlagen",
    "passwort erforderlich",
    # === Spanish locale ===
    "contraseña incorrecta",
    "fallo de autenticación",
    "contraseña requerida",
    # === Portuguese locale ===
    "senha incorreta",
    "falha de autenticação",
    # === Italian locale ===
    "password errata",
    "autenticazione fallita",
    # === Russian locale ===
    "неверный пароль",
    "ошибка аутентификации",
    # === Chinese locale ===
    "密码错误",
    "认证失败",
    # === Japanese locale ===
    "パスワードが違います",
    "認証に失敗",
)

# Permission error indicators (triggers auto-elevation)
PERMISSION_ERROR_PATTERNS: tuple[str, ...] = (
    # Standard Unix/Linux
    "permission denied",
    "operation not permitted",
    "access denied",
    # Systemd/Polkit (common on modern Linux)
    "interactive authentication required",
    "authentication required",
    "authorization required",
    "not authorized",
    "access is denied",
    # Root-required commands
    "must be root",
    "requires root",
    "only root can",
    "need to be root",
    "run as root",
    # Sudo-specific
    "sudo:",
    "a password is required",
)

# Keywords that indicate elevation methods (not jump hosts)
ELEVATION_KEYWORDS: frozenset[str] = frozenset(
    {"sudo", "su", "doas", "root", "admin", "elevate", "privilege"}
)

# Prefixes that LLM might incorrectly add to commands
SUDO_PREFIXES: tuple[str, ...] = (
    "sudo -n ",
    "sudo ",
    "doas ",
    "su -c ",
)

# Password-based elevation methods
PASSWORD_METHODS: tuple[str, ...] = (
    "su",
    "sudo_with_password",
    "doas_with_password",
)


# Elevation method detection cache (host -> method)
# Methods: "sudo" (passwordless), "sudo-S" (with password), "su", "doas", None (unknown)
# Thread-safe: accessed from multiple async contexts
_elevation_method_cache: dict[str, str | None] = {}
_elevation_method_cache_lock = threading.Lock()


def get_cached_elevation_method(host: str) -> str | None:
    """Get cached elevation method for a host (thread-safe)."""
    from loguru import logger

    with _elevation_method_cache_lock:
        method = _elevation_method_cache.get(host)
    if method is None:
        logger.debug(f"🔍 No cached elevation method for {host}")
    return method


def set_cached_elevation_method(host: str, method: str | None) -> None:
    """Cache the elevation method for a host (thread-safe)."""
    with _elevation_method_cache_lock:
        _elevation_method_cache[host] = method


def clear_elevation_method_cache(host: str | None = None) -> None:
    """Clear elevation method cache for a host or all hosts (thread-safe)."""
    with _elevation_method_cache_lock:
        if host:
            _elevation_method_cache.pop(host, None)
        else:
            _elevation_method_cache.clear()


def format_elevated_command(command: str, method: str) -> str:
    """
    Format a command with the appropriate elevation prefix.

    Args:
        command: Base command to execute.
        method: Elevation method ("sudo", "sudo-S", "su", "doas").

    Returns:
        Command with appropriate elevation prefix.
    """
    # Strip existing elevation prefixes
    clean_cmd = command.strip()
    for prefix in SUDO_PREFIXES:
        if clean_cmd.lower().startswith(prefix.lower()):
            clean_cmd = clean_cmd[len(prefix) :].strip()

    if method == "sudo":
        return f"sudo {clean_cmd}"
    elif method == "sudo-S":
        return f"sudo -S {clean_cmd}"
    elif method == "su":
        # Use shlex.quote for robust shell escaping
        return f"su -c {shlex.quote(clean_cmd)}"
    elif method == "doas":
        return f"doas {clean_cmd}"
    else:
        return clean_cmd


async def detect_elevation_method(
    execute_fn: SSHExecutor,
    host: str,
) -> str | None:
    """
    Detect the best elevation method for a host.

    Probes the host to determine which elevation method is available:
    1. sudo -n (passwordless sudo)
    2. sudo (with password)
    3. su (with password)
    4. doas

    Args:
        execute_fn: Async function to execute SSH commands.
                   Signature: async (host, command, timeout) -> result with exit_code
        host: Target host.

    Returns:
        Elevation method: "sudo", "sudo-S", "su", "doas", or None if unknown.
    """
    from loguru import logger

    # Check cache first
    cached = get_cached_elevation_method(host)
    if cached is not None:
        logger.debug(f"🔑 Using cached elevation method for {host}: {cached}")
        return cached

    logger.debug(f"🔍 Detecting elevation method for {host}...")

    # Test methods in order of preference
    tests = [
        # (command, method_if_success, description)
        ("sudo -n true 2>/dev/null", "sudo", "passwordless sudo"),
        ("which sudo >/dev/null 2>&1", "sudo-S", "sudo with password"),
        ("which su >/dev/null 2>&1", "su", "su"),
        ("which doas >/dev/null 2>&1", "doas", "doas"),
    ]

    for test_cmd, method, desc in tests:
        try:
            result = await execute_fn(host, test_cmd, 10)
            exit_code = getattr(result, "exit_code", -1)
            if hasattr(result, "data") and result.data:
                exit_code = result.data.get("exit_code", exit_code)

            if exit_code == 0:
                logger.info(f"🔑 Elevation method for {host}: {method} ({desc})")
                set_cached_elevation_method(host, method)
                return method
        except Exception as e:
            logger.debug(f"Test '{test_cmd}' failed on {host}: {e}")
            continue

    # No method found
    logger.warning(f"⚠️ No elevation method detected for {host}")
    set_cached_elevation_method(host, "")  # Empty string = tested but none found
    return None


class ExpectedExitCode(NamedTuple):
    """Commands with expected non-zero exit codes."""

    pattern: str  # Regex pattern to match command
    expected_codes: tuple[int, ...]  # Exit codes that are NOT failures
    description: str  # Why these exit codes are normal


# Commands where non-zero exit codes are normal behavior, NOT errors
# These should NOT trigger loop detection failure counting
EXPECTED_NONZERO_EXIT_COMMANDS: tuple[ExpectedExitCode, ...] = (
    # systemctl is-active returns 1/3/4 for inactive/unknown services
    ExpectedExitCode(
        pattern=r"systemctl\s+(is-active|is-enabled|is-failed)",
        expected_codes=(1, 3, 4),
        description="Service status check (inactive/disabled/unknown)",
    ),
    # grep returns 1 if no match found (normal behavior)
    ExpectedExitCode(
        pattern=r"\bgrep\b",
        expected_codes=(1,),
        description="No matches found",
    ),
    # test/[ returns 1 if condition is false
    ExpectedExitCode(
        pattern=r"^(test\s|\[\s)",
        expected_codes=(1,),
        description="Condition evaluated to false",
    ),
    # diff returns 1 if files differ
    ExpectedExitCode(
        pattern=r"\bdiff\b",
        expected_codes=(1,),
        description="Files are different",
    ),
    # which/type returns 1 if command not found
    ExpectedExitCode(
        pattern=r"^(which|type|command\s+-v)\s",
        expected_codes=(1,),
        description="Command not found",
    ),
    # pgrep returns 1 if no processes match
    ExpectedExitCode(
        pattern=r"\bpgrep\b",
        expected_codes=(1,),
        description="No matching processes",
    ),
    # curl with --fail returns non-zero on HTTP errors (expected for health checks)
    ExpectedExitCode(
        pattern=r"curl\s.*--fail",
        expected_codes=(22,),
        description="HTTP error response",
    ),
)


def needs_elevation(stderr: str) -> bool:
    """Check if stderr indicates a permission error requiring elevation."""
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in PERMISSION_ERROR_PATTERNS)


def is_auth_error(stderr: str) -> bool:
    """Check if stderr indicates an authentication error.

    Distinguishes between:
    - Auth failures from sudo/su (wrong password, not in sudoers, etc.)
    - File system permission errors from shell redirections (not auth failures)
    """
    stderr_lower = stderr.lower()

    # Shell permission errors on FILES are NOT auth failures
    # These happen when shell redirection (>) fails before sudo runs
    # Formats:
    #   zsh:1: permission denied: /etc/foo
    #   bash: /etc/foo: Permission denied
    #   -bash: /etc/passwd: Permission denied
    #   sh: /root/.bashrc: Permission denied

    # Pattern 1: shell: path: Permission denied (bash style)
    # Pattern 2: shell: permission denied: path (zsh style)
    shell_file_error = re.search(
        r"^-?(zsh|bash|sh|ksh|fish|dash)(\:\d+)?:\s*([/~][^:]*:\s*)?permission denied",
        stderr_lower,
    )
    if shell_file_error:
        return False

    return any(pattern in stderr_lower for pattern in AUTH_ERROR_PATTERNS)


def strip_sudo_prefix(command: str) -> tuple[str, str | None]:
    """
    Strip sudo/doas/su prefix from command if present.

    Returns:
        Tuple of (cleaned_command, stripped_prefix or None).
    """
    for prefix in SUDO_PREFIXES:
        if command.lower().startswith(prefix):
            return command[len(prefix) :].lstrip(), prefix.strip()
    return command, None


def is_expected_exit_code(command: str, exit_code: int) -> bool:
    """
    Check if the exit code is expected (not an error) for this command.

    Many commands return non-zero exit codes for normal conditions:
    - systemctl is-active: returns 1/3/4 for inactive/unknown services
    - grep: returns 1 if no matches found
    - test/[: returns 1 if condition is false

    These should NOT be counted as failures for loop detection.

    Args:
        command: The command that was executed.
        exit_code: The exit code returned.

    Returns:
        True if this exit code is expected behavior, False if it's a real error.
    """
    if exit_code == 0:
        return True  # Success is always expected

    for expected in EXPECTED_NONZERO_EXIT_COMMANDS:
        pattern_match = re.search(expected.pattern, command, re.IGNORECASE)
        if pattern_match and exit_code in expected.expected_codes:
            return True

    return False


def should_trigger_elevation(command: str, exit_code: int, stderr: str) -> bool:
    """
    Determine if a command failure should trigger privilege elevation.

    This is more nuanced than just checking stderr:
    - systemctl is-active returning 1 is NOT a permission error
    - grep returning 1 is NOT a permission error
    - Only trigger elevation if stderr actually contains permission patterns

    Args:
        command: The command that was executed.
        exit_code: The exit code returned.
        stderr: The stderr output.

    Returns:
        True if elevation should be attempted.
    """
    # Success never needs elevation
    if exit_code == 0:
        return False

    # Expected exit codes for this command don't need elevation
    if is_expected_exit_code(command, exit_code):
        return False

    # Only trigger elevation if stderr indicates permission issues
    return needs_elevation(stderr)
