"""
Merlya Tools - SSH error detection patterns.

Constants for detecting permission errors and authentication failures.
"""

from __future__ import annotations

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


def needs_elevation(stderr: str) -> bool:
    """Check if stderr indicates a permission error requiring elevation."""
    stderr_lower = stderr.lower()
    return any(pattern in stderr_lower for pattern in PERMISSION_ERROR_PATTERNS)


def is_auth_error(stderr: str) -> bool:
    """Check if stderr indicates an authentication error."""
    stderr_lower = stderr.lower()
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
