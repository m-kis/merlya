"""
Merlya Tools - System validation module.

Provides validation functions for system tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import re

# Validation patterns
_VALID_SERVICE_NAME = re.compile(r"^[a-zA-Z0-9_.-]+$")
_VALID_LOG_LEVEL = ("error", "warn", "info", "debug")
_MAX_PATH_LENGTH = 4096
_MAX_PATTERN_LENGTH = 256


def _validate_path(path: str) -> str | None:
    """Validate file path. Returns error message or None if valid."""
    if not path:
        return "Path cannot be empty"
    if len(path) > _MAX_PATH_LENGTH:
        return f"Path too long (max {_MAX_PATH_LENGTH} chars)"
    if "\x00" in path:
        return "Path contains null bytes"
    return None


def _validate_service_name(name: str) -> str | None:
    """Validate service name. Returns error message or None if valid."""
    if not name:
        return "Service name cannot be empty"
    if len(name) > 128:
        return "Service name too long (max 128 chars)"
    if not _VALID_SERVICE_NAME.match(name):
        return f"Invalid service name: {name} (only alphanumeric, -, _, . allowed)"
    return None


def _validate_username(user: str | None) -> str | None:
    """Validate username. Returns error message or None if valid."""
    if not user:
        return None  # Optional
    if len(user) > 32:
        return "Username too long (max 32 chars)"
    if not re.match(r"^[a-zA-Z0-9_-]+$", user):
        return f"Invalid username: {user}"
    return None


def _validate_threshold(threshold: int) -> str | None:
    """Validate threshold value. Returns error message or None if valid."""
    if not (0 <= threshold <= 100):
        return "Threshold must be 0-100"
    return None


def _validate_log_level(level: str) -> str | None:
    """Validate log level. Returns error message or None if valid."""
    if level.lower() not in _VALID_LOG_LEVEL:
        return f"Invalid level: {level} (use: {', '.join(_VALID_LOG_LEVEL)})"
    return None


def _validate_pattern_length(pattern: str) -> str | None:
    """Validate pattern length. Returns error message or None if valid."""
    if len(pattern) > _MAX_PATTERN_LENGTH:
        return f"Pattern too long (max {_MAX_PATTERN_LENGTH} chars)"
    return None


def _validate_lines_count(lines: int) -> str | None:
    """Validate lines count. Returns error message or None if valid."""
    if not (1 <= lines <= 10000):
        return "Lines must be 1-10000"
    return None
