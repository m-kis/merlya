"""
AutoGen tool wrappers for Athena.

BACKWARD COMPATIBILITY LAYER
============================
This file now re-exports tools from athena_ai.tools module.
All tool implementations have been moved to separate modules following SRP:

- tools/base.py: ToolContext, validation, hooks
- tools/commands.py: execute_command, add_route
- tools/hosts.py: list_hosts, scan_host, check_permissions
- tools/security.py: audit_host, analyze_security_logs
- tools/files.py: read/write files, grep, find, tail
- tools/system.py: disk, memory, network, processes, services
- tools/containers.py: docker_exec, kubectl_exec
- tools/web.py: web_search, web_fetch
- tools/interaction.py: ask_user, remember_skill, recall_skill

For new code, import directly from athena_ai.tools:
    from athena_ai.tools import execute_command, list_hosts
"""
# Re-export everything for backward compatibility
from athena_ai.tools import (
    ToolContext,
    add_route,
    analyze_security_logs,
    ask_user,
    audit_host,
    check_permissions,
    disk_info,
    docker_exec,
    emit_hook,
    execute_command,
    find_file,
    get_infrastructure_context,
    get_tool_context,
    glob_files,
    grep_files,
    initialize_tools,
    kubectl_exec,
    list_hosts,
    memory_info,
    network_connections,
    process_list,
    read_remote_file,
    recall_skill,
    remember_skill,
    scan_host,
    service_control,
    tail_logs,
    validate_host,
    web_fetch,
    web_search,
    write_remote_file,
)

# Backward compatibility aliases
initialize_autogen_tools = initialize_tools
_validate_host = validate_host
_emit_hook = emit_hook

__all__ = [
    # Initialization
    "initialize_autogen_tools",
    "initialize_tools",
    "ToolContext",
    "get_tool_context",
    # Validation & hooks
    "validate_host",
    "_validate_host",
    "emit_hook",
    "_emit_hook",
    # Commands
    "execute_command",
    "add_route",
    # Hosts
    "get_infrastructure_context",
    "list_hosts",
    "scan_host",
    "check_permissions",
    # Security
    "audit_host",
    "analyze_security_logs",
    # Files
    "read_remote_file",
    "glob_files",
    "grep_files",
    "find_file",
    "write_remote_file",
    "tail_logs",
    # System
    "disk_info",
    "memory_info",
    "network_connections",
    "process_list",
    "service_control",
    # Containers
    "docker_exec",
    "kubectl_exec",
    # Web
    "web_search",
    "web_fetch",
    # Interaction
    "ask_user",
    "remember_skill",
    "recall_skill",
]
