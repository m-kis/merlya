"""
Built-in Merlya Tools.

Modular tool implementations following SRP and SoC principles.
Split from autogen_tools.py into focused modules.
"""
# High-level generation tools
# Base utilities
from .base import (
    StatusManager,
    ToolContext,
    emit_hook,
    get_status_manager,
    get_tool_context,
    initialize_tools,
    validate_host,
)
from .cicd import (
    CI_TOOLS,
    analyze_ci_failure,
    cancel_ci_run,
    check_ci_permissions,
    debug_most_recent_failure,
    get_ci_status,
    list_ci_runs,
    list_ci_workflows,
    retry_ci_run,
    trigger_ci_workflow,
)

# Modular tools
from .commands import add_route, execute_command
from .containers import docker_exec, kubectl_exec
from .files import (
    find_file,
    glob_files,
    grep_files,
    read_remote_file,
    tail_logs,
    write_remote_file,
)
from .hosts import (
    check_permissions,
    get_infrastructure_context,
    list_hosts,
    scan_host,
)
from .infra_tools import (
    GenerateAnsibleTool,
    GenerateDockerfileTool,
    GenerateTerraformTool,
    PreviewFileEditTool,
    RollbackTool,
)
from .interaction import ask_user, recall_skill, remember_skill, request_elevation
from .security import analyze_security_logs, audit_host
from .system import (
    disk_info,
    memory_info,
    network_connections,
    process_list,
    service_control,
)
from .web import web_fetch, web_search

__all__ = [
    # Generation tools
    "GenerateTerraformTool",
    "GenerateAnsibleTool",
    "GenerateDockerfileTool",
    "PreviewFileEditTool",
    "RollbackTool",
    # Base
    "StatusManager",
    "ToolContext",
    "get_status_manager",
    "get_tool_context",
    "initialize_tools",
    "validate_host",
    "emit_hook",
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
    "request_elevation",
    # CI/CD
    "get_ci_status",
    "list_ci_workflows",
    "list_ci_runs",
    "analyze_ci_failure",
    "trigger_ci_workflow",
    "retry_ci_run",
    "cancel_ci_run",
    "check_ci_permissions",
    "debug_most_recent_failure",
    "CI_TOOLS",
]
