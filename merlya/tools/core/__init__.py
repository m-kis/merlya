"""
Merlya Tools - Core tools (always active).

Includes: list_hosts, get_host, ssh_execute, bash_execute, ask_user, request_confirmation.
"""

# Models
# Bash execution
from merlya.tools.core.bash import bash_execute

# Host tools
from merlya.tools.core.hosts import get_host, list_hosts
from merlya.tools.core.models import ToolResult

# Resolution
from merlya.tools.core.resolve import (
    REFERENCE_PATTERN,
    get_resolved_host_names,
    resolve_host_references,
    resolve_secrets,
)

# Security
from merlya.tools.core.security import (
    DANGEROUS_COMMANDS,
    UNSAFE_PASSWORD_PATTERNS,
    detect_unsafe_password,
    is_dangerous_command,
)

# SSH execution
from merlya.tools.core.ssh import ssh_execute

# User interaction
from merlya.tools.core.user_input import (
    ask_user,
    request_confirmation,
    request_credentials,
    request_elevation,
)

# Variables
from merlya.tools.core.variables import get_variable, set_variable

__all__ = [
    # Security
    "DANGEROUS_COMMANDS",
    # Resolution
    "REFERENCE_PATTERN",
    "UNSAFE_PASSWORD_PATTERNS",
    # Models
    "ToolResult",
    # User interaction
    "ask_user",
    # Bash execution
    "bash_execute",
    "detect_unsafe_password",
    # Host tools
    "get_host",
    "get_resolved_host_names",
    # Variables
    "get_variable",
    "is_dangerous_command",
    "list_hosts",
    "request_confirmation",
    "request_credentials",
    "request_elevation",
    "resolve_host_references",
    "resolve_secrets",
    "set_variable",
    # SSH execution
    "ssh_execute",
]
