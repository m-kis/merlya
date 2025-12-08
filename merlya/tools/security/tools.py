"""
Merlya Tools - Security operations.

Provides tools for security auditing and monitoring on remote hosts.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.

This module re-exports all security tools from submodules for backwards compatibility.
"""

from merlya.tools.security.base import (
    DEFAULT_TIMEOUT,
    PortInfo,
    SecurityResult,
    SSHKeyInfo,
    execute_security_command,
)
from merlya.tools.security.config import check_security_config
from merlya.tools.security.keys import audit_ssh_keys
from merlya.tools.security.monitoring import (
    check_critical_services,
    check_failed_logins,
    check_pending_updates,
)
from merlya.tools.security.ports import check_open_ports
from merlya.tools.security.users import check_sudo_config, check_users

# Backwards compatibility alias
_execute_command = execute_security_command

__all__ = [
    "DEFAULT_TIMEOUT",
    "PortInfo",
    "SSHKeyInfo",
    "SecurityResult",
    "audit_ssh_keys",
    "check_critical_services",
    "check_failed_logins",
    "check_open_ports",
    "check_pending_updates",
    "check_security_config",
    "check_sudo_config",
    "check_users",
    "execute_security_command",
]
