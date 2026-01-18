"""
Merlya Audit - Formatters and sanitizers.

Contains sensitive data detection and sanitization for audit logging.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns for detecting sensitive keys (case-insensitive substring match)
_SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    # Passwords
    "password",
    "passwd",
    "pwd",
    # Secrets and keys
    "secret",
    "key",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "private_key",
    "privatekey",
    # Authentication
    "auth",
    "credential",
    "bearer",
    "jwt",
    "oauth",
    # Session and identity
    "session",
    "cookie",
    "csrf",
    "nonce",
    # Certificates
    "cert",
    "certificate",
    "pem",
    # Connection strings and DSNs
    "connection_string",
    "connectionstring",
    "dsn",
    "database_url",
    "db_url",
    # Cloud provider specific
    "aws_secret",
    "azure_key",
    "gcp_key",
    # SSH
    "ssh_key",
    "id_rsa",
    "id_ed25519",
    # Encryption
    "encrypt",
    "decrypt",
    "salt",
    "iv",
    "hmac",
)

# Regex patterns for detecting sensitive values (regardless of key name)
_SENSITIVE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # AWS access key IDs (start with AKIA, ABIA, ACCA, ASIA)
    re.compile(r"^A[KBS]IA[A-Z0-9]{16}$"),
    # AWS secret access keys (40 char base64-ish)
    re.compile(r"^[A-Za-z0-9/+=]{40}$"),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    re.compile(r"^gh[pousr]_[A-Za-z0-9_]{36,}$"),
    # Generic API keys (long alphanumeric strings, 32+ chars)
    re.compile(r"^[A-Za-z0-9_-]{32,}$"),
    # JWT tokens (three base64 parts separated by dots)
    re.compile(r"^eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*$"),
    # Bearer tokens
    re.compile(r"^Bearer\s+.{20,}$", re.IGNORECASE),
    # Basic auth (base64 encoded user:pass)
    re.compile(r"^Basic\s+[A-Za-z0-9+/=]{10,}$", re.IGNORECASE),
    # Private keys (PEM format indicators)
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
    # Hex-encoded secrets (32+ hex chars, likely hashes or keys)
    re.compile(r"^[a-fA-F0-9]{32,}$"),
)


def is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in _SENSITIVE_KEY_PATTERNS)


def is_sensitive_value(value: str) -> bool:
    """Check if a string value looks like sensitive data."""
    if not isinstance(value, str) or len(value) < 16:
        # Short strings are unlikely to be secrets
        return False
    return any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS)


def sanitize_value(value: Any) -> Any:
    """Sanitize a single value, checking if it looks like sensitive data."""
    if isinstance(value, str) and is_sensitive_value(value):
        return "[REDACTED]"
    return value


def sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitize sensitive data from args dictionary.

    Sanitizes based on:
    1. Key names that match sensitive patterns (case-insensitive)
    2. String values that look like secrets (API keys, tokens, etc.)
    """
    sanitized: dict[str, Any] = {}
    for k, v in args.items():
        if is_sensitive_key(k):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_args(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_args(item) if isinstance(item, dict) else sanitize_value(item)
                for item in v
            ]
        elif isinstance(v, str):
            sanitized[k] = sanitize_value(v)
        else:
            sanitized[k] = v
    return sanitized


__all__ = [
    "is_sensitive_key",
    "is_sensitive_value",
    "sanitize_args",
    "sanitize_value",
]
