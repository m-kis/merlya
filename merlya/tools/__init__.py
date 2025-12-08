"""
Merlya Tools - Agent tools for PydanticAI.

Tools are grouped by category:
- core: Host management, SSH execution, variables
- system: System info, disk, memory, CPU, processes
- files: File operations (read, write, list, search)
- security: Security auditing (ports, keys, config)
"""

from merlya.tools.core import (
    ToolResult,
    ask_user,
    get_host,
    get_variable,
    list_hosts,
    request_confirmation,
    set_variable,
    ssh_execute,
)
from merlya.tools.files import (
    FileResult,
    delete_file,
    file_exists,
    file_info,
    list_directory,
    read_file,
    search_files,
    write_file,
)
from merlya.tools.security import (
    SecurityResult,
    audit_ssh_keys,
    check_open_ports,
    check_security_config,
    check_sudo_config,
    check_users,
)
from merlya.tools.system import (
    analyze_logs,
    check_cpu,
    check_disk_usage,
    check_memory,
    check_service_status,
    get_system_info,
    list_processes,
)
from merlya.tools.web import search_web

__all__ = [
    # Files
    "FileResult",
    # Security
    "SecurityResult",
    # Core
    "ToolResult",
    # System
    "analyze_logs",
    "ask_user",
    "audit_ssh_keys",
    "check_cpu",
    "check_disk_usage",
    "check_memory",
    "check_open_ports",
    "check_security_config",
    "check_service_status",
    "check_sudo_config",
    "check_users",
    "delete_file",
    "file_exists",
    "file_info",
    "get_host",
    "get_system_info",
    "get_variable",
    "list_directory",
    "list_hosts",
    "list_processes",
    "read_file",
    "request_confirmation",
    "search_files",
    "search_web",
    "set_variable",
    "ssh_execute",
    "write_file",
]
