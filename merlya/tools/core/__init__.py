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
    resolve_all_references,
    resolve_host_references,
    resolve_secrets,
)

# Security
from merlya.tools.core.security import (
    DANGEROUS_COMMAND_PATTERNS,
    DANGEROUS_COMMANDS,
    UNSAFE_PASSWORD_PATTERNS,
    detect_unsafe_password,
    is_dangerous_command,
)

# SSH execution
from merlya.tools.core.ssh import (
    clear_credential_hints,
    get_credential_hint,
    set_credential_hint,
    ssh_execute,
)

# User interaction
from merlya.tools.core.user_input import (
    ask_user,
    request_confirmation,
    request_credentials,
    request_elevation,
)

# Variables
from merlya.tools.core.variables import DANGEROUS_ENV_VARS, get_variable, set_variable

__all__ = [
    "DANGEROUS_COMMANDS",
    # Security constants
    "DANGEROUS_COMMAND_PATTERNS",
    "DANGEROUS_ENV_VARS",
    # Resolution
    "REFERENCE_PATTERN",
    "UNSAFE_PASSWORD_PATTERNS",
    # Models
    "ToolResult",
    # User interaction
    "ask_user",
    # Execution
    "bash_execute",
    # Credential hints
    "clear_credential_hints",
    # Security functions
    "detect_unsafe_password",
    # Credential hints
    "get_credential_hint",
    # Host tools
    "get_host",
    # Resolution functions
    "get_resolved_host_names",
    # Variables
    "get_variable",
    "is_dangerous_command",
    "list_hosts",
    "request_confirmation",
    "request_credentials",
    "request_elevation",
    "resolve_all_references",
    "resolve_host_references",
    "resolve_secrets",
    # Credential hints
    "set_credential_hint",
    "set_variable",
    "ssh_execute",
]
