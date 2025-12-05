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

__all__ = [
    # Core
    "ToolResult",
    "ask_user",
    "get_host",
    "get_variable",
    "list_hosts",
    "request_confirmation",
    "set_variable",
    "ssh_execute",
    # System
    "analyze_logs",
    "check_cpu",
    "check_disk_usage",
    "check_memory",
    "check_service_status",
    "get_system_info",
    "list_processes",
    # Files
    "FileResult",
    "delete_file",
    "file_exists",
    "file_info",
    "list_directory",
    "read_file",
    "search_files",
    "write_file",
    # Security
    "SecurityResult",
    "audit_ssh_keys",
    "check_open_ports",
    "check_security_config",
    "check_sudo_config",
    "check_users",
]
