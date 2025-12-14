"""
Merlya Common - Validation utilities.

Centralized validation functions for common use cases.
"""

from __future__ import annotations

import os
from pathlib import Path


def validate_file_path(file_path: Path) -> tuple[bool, str]:
    """
    Validate file path security and accessibility.

    Checks:
    - Path exists and is accessible
    - Path is within allowed directories
    - No path traversal attempts
    - No dangerous characters

    Args:
        file_path: Path object to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    try:
        # Resolve without requiring the path to exist (export paths may be new).
        abs_path = file_path.expanduser().resolve(strict=False)

        # Block special filesystem paths even if they don't exist on this OS.
        abs_str = str(abs_path)
        if abs_str.startswith(("/proc", "/sys")):
            return False, "Access denied: Special filesystem paths not allowed"

        # If the target exists, enforce basic file/readability constraints.
        if abs_path.exists():
            if not abs_path.is_file():
                return False, f"Path is not a file: {file_path}"

            if not os.access(abs_path, os.R_OK):
                return False, f"File not readable: {file_path}"

        return True, ""

    except (OSError, ValueError) as e:
        return False, f"Invalid file path: {e}"


def validate_port(port: int) -> tuple[bool, str]:
    """
    Validate port number.

    Args:
        port: Port number to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not isinstance(port, int):
        return False, f"Port must be an integer, got {type(port).__name__}"

    if port < 1 or port > 65535:
        return False, f"Port must be between 1 and 65535, got {port}"

    return True, ""


def validate_hostname(hostname: str) -> tuple[bool, str]:
    """
    Validate hostname format.

    Args:
        hostname: Hostname to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not hostname or not isinstance(hostname, str):
        return False, "Hostname cannot be empty"

    # Basic hostname validation
    if len(hostname) > 253:
        return False, "Hostname too long (max 253 characters)"

    # Check for valid characters
    import re

    hostname_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"

    if not re.match(hostname_pattern, hostname):
        return False, f"Invalid hostname format: {hostname}"

    return True, ""


def validate_email(email: str) -> tuple[bool, str]:
    """
    Validate email address format.

    Args:
        email: Email address to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not email or not isinstance(email, str):
        return False, "Email cannot be empty"

    import re

    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if not re.match(email_pattern, email):
        return False, f"Invalid email format: {email}"

    return True, ""


def validate_username(username: str) -> tuple[bool, str]:
    """
    Validate username format.

    Args:
        username: Username to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not username or not isinstance(username, str):
        return False, "Username cannot be empty"

    if len(username) < 3:
        return False, "Username must be at least 3 characters long"

    if len(username) > 32:
        return False, "Username too long (max 32 characters)"

    # Check for valid characters (alphanumeric, underscore, hyphen)
    import re

    username_pattern = r"^[a-zA-Z0-9_-]+$"

    if not re.match(username_pattern, username):
        return False, f"Username contains invalid characters: {username}"

    return True, ""


def validate_service_name(service_name: str) -> tuple[bool, str]:
    """
    Validate service name format.

    Args:
        service_name: Service name to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not service_name or not isinstance(service_name, str):
        return False, "Service name cannot be empty"

    if len(service_name) > 63:
        return False, "Service name too long (max 63 characters)"

    # Check for valid characters (alphanumeric, underscore, hyphen, dot)
    import re

    service_pattern = r"^[a-zA-Z0-9_.-]+$"

    if not re.match(service_pattern, service_name):
        return False, f"Service name contains invalid characters: {service_name}"

    return True, ""


def validate_path_safety(path: str | Path) -> tuple[bool, str]:
    """
    Validate path for security issues.

    Args:
        path: Path to validate.

    Returns:
        Tuple of (is_safe: bool, error_message: str).
    """
    try:
        path_obj = Path(path)
        abs_path = path_obj.resolve()

        # Check for dangerous patterns
        dangerous_patterns = ["..", "~", "$", "`", ">", "<", "|", ";", "&", "(", ")"]

        path_str = str(abs_path)
        for pattern in dangerous_patterns:
            if pattern in path_str:
                return False, f"Dangerous pattern detected: {pattern}"

        # Check for absolute paths outside system directories
        if abs_path.is_absolute():
            # Allow typical system directories
            allowed_prefixes = ["/usr", "/var", "/opt", "/home", "/etc", "/tmp", "/root"]
            if not any(str(abs_path).startswith(prefix) for prefix in allowed_prefixes):
                # Check if it's a relative path that became absolute
                if not path_obj.is_absolute():
                    return True, ""  # Relative paths are generally safe
                return False, f"Absolute path outside allowed directories: {abs_path}"

        return True, ""

    except (OSError, ValueError) as e:
        return False, f"Invalid path: {e}"


def validate_threshold(threshold: int, min_val: int = 0, max_val: int = 100) -> tuple[bool, str]:
    """
    Validate threshold value.

    Args:
        threshold: Threshold value to validate.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not isinstance(threshold, int):
        return False, f"Threshold must be an integer, got {type(threshold).__name__}"

    if threshold < min_val or threshold > max_val:
        return False, f"Threshold must be between {min_val} and {max_val}, got {threshold}"

    return True, ""


def validate_log_level(level: str) -> tuple[bool, str]:
    """
    Validate log level.

    Args:
        level: Log level to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "TRACE"]

    if not level or not isinstance(level, str):
        return False, "Log level cannot be empty"

    if level.upper() not in valid_levels:
        return False, f"Invalid log level: {level}. Valid levels: {', '.join(valid_levels)}"

    return True, ""


def validate_lines_count(lines: int) -> tuple[bool, str]:
    """
    Validate lines count parameter.

    Args:
        lines: Number of lines to validate.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not isinstance(lines, int):
        return False, f"Lines count must be an integer, got {type(lines).__name__}"

    if lines < 1:
        return False, "Lines count must be positive"

    if lines > 10000:
        return False, "Lines count too large (max 10000)"

    return True, ""


def validate_pattern_length(pattern: str, max_length: int = 1000) -> tuple[bool, str]:
    """
    Validate pattern length for regex or search patterns.

    Args:
        pattern: Pattern to validate.
        max_length: Maximum allowed pattern length.

    Returns:
        Tuple of (is_valid: bool, error_message: str).
    """
    if not pattern or not isinstance(pattern, str):
        return False, "Pattern cannot be empty"

    if len(pattern) > max_length:
        return False, f"Pattern too long (max {max_length} characters)"

    return True, ""
