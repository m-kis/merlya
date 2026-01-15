"""
Merlya Agent - Type definitions.

TypedDict definitions for tool results and agent dependencies.
These types replace `Any` usage throughout the codebase for better type safety.
"""

from __future__ import annotations

from typing import TypedDict

# =============================================================================
# SSH/Bash Result Types
# =============================================================================


class SSHResultData(TypedDict, total=False):
    """Data returned from SSH command execution."""

    stdout: str
    stderr: str
    exit_code: int
    command: str
    via: str | None
    host: str
    timeout: int
    needs_credentials: bool
    non_interactive: bool
    permanent_failure: bool
    suggestions: list[str]


class BashResultData(TypedDict, total=False):
    """Data returned from local bash command execution."""

    stdout: str
    stderr: str
    exit_code: int
    command: str
    timeout: int


class SSHExecuteResponse(TypedDict, total=False):
    """Response from ssh_execute tool (agent-facing)."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    via: str | None
    loop_detected: bool
    circuit_breaker: bool
    error: str | None
    verification: VerificationInfo


class BashResponse(TypedDict, total=False):
    """Response from bash tool (agent-facing)."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    loop_detected: bool
    error: str | None


class VerificationInfo(TypedDict):
    """Verification hint for state-changing commands."""

    command: str
    expect: str
    description: str


# =============================================================================
# Host Types
# =============================================================================


class HostListItem(TypedDict, total=False):
    """Host item in list_hosts response."""

    name: str
    hostname: str
    status: str | None
    tags: list[str]
    last_seen: str | None
    elevation_method: str | None


class HostInfo(TypedDict, total=False):
    """Detailed host information from get_host."""

    id: str
    name: str
    hostname: str
    port: int
    username: str | None
    tags: list[str]
    health_status: str | None
    last_seen: str | None
    elevation_method: str | None
    metadata: dict[str, object]
    os_info: OSInfo | None


class OSInfo(TypedDict, total=False):
    """Operating system information."""

    name: str
    version: str
    kernel: str
    arch: str


class HostsListResponse(TypedDict):
    """Response from list_hosts tool."""

    hosts: list[HostListItem]
    count: int
    error: str | None


class HostResponse(TypedDict, total=False):
    """Response from get_host tool - can be HostInfo or error."""

    # HostInfo fields
    id: str
    name: str
    hostname: str
    port: int
    username: str | None
    tags: list[str]
    health_status: str | None
    last_seen: str | None
    elevation_method: str | None
    metadata: dict[str, object]
    os_info: OSInfo | None
    # Error case
    error: str | None


# =============================================================================
# MCP Tool Types
# =============================================================================


class MCPToolInfo(TypedDict, total=False):
    """Information about an MCP tool."""

    name: str
    description: str
    server: str
    parameters: dict[str, object]
    required_params: list[str]


class MCPToolsListResponse(TypedDict):
    """Response from list_mcp_tools."""

    tools: list[MCPToolInfo]
    count: int


class MCPCallResponse(TypedDict, total=False):
    """Response from call_mcp_tool."""

    success: bool
    result: object
    error: str | None


# =============================================================================
# Security Tool Types
# =============================================================================


class PortInfo(TypedDict):
    """Information about an open port."""

    port: int
    protocol: str
    state: str
    process: str | None
    pid: int | None


class OpenPortsResponse(TypedDict, total=False):
    """Response from check_open_ports."""

    ports: list[PortInfo]
    severity: str | None
    error: str | None


class SSHKeyInfo(TypedDict, total=False):
    """SSH key audit information."""

    type: str
    bits: int
    fingerprint: str
    comment: str
    issues: list[str]


class SSHKeyAuditResponse(TypedDict, total=False):
    """Response from audit_ssh_keys."""

    audit: list[SSHKeyInfo]
    severity: str | None
    error: str | None


class SecurityConfigResponse(TypedDict, total=False):
    """Response from check_security_config."""

    config: dict[str, object]
    severity: str | None
    error: str | None


class UserInfo(TypedDict, total=False):
    """User account information."""

    username: str
    uid: int
    gid: int
    home: str
    shell: str
    groups: list[str]
    last_login: str | None
    issues: list[str]


class UsersAuditResponse(TypedDict, total=False):
    """Response from check_users."""

    users: list[UserInfo]
    severity: str | None
    error: str | None


class SudoConfigResponse(TypedDict, total=False):
    """Response from check_sudo_config."""

    config: dict[str, object]
    severity: str | None
    error: str | None


# =============================================================================
# System Tool Types
# =============================================================================


class SystemInfo(TypedDict, total=False):
    """System information response."""

    os: str
    kernel: str
    arch: str
    hostname: str
    uptime: str
    load_avg: list[float]
    error: str | None


class DiskUsageInfo(TypedDict):
    """Disk usage for a mount point."""

    filesystem: str
    size: str
    used: str
    available: str
    use_percent: str
    mounted_on: str


class DiskUsageResponse(TypedDict, total=False):
    """Response from check_disk_usage."""

    filesystems: list[DiskUsageInfo]
    error: str | None


class MemoryInfo(TypedDict, total=False):
    """Memory information."""

    total: str
    used: str
    free: str
    available: str
    swap_total: str
    swap_used: str
    swap_free: str
    error: str | None


class CPUInfo(TypedDict, total=False):
    """CPU information."""

    cpu_count: int
    model: str
    usage_percent: float
    load_avg: list[float]
    error: str | None


class ServiceStatus(TypedDict, total=False):
    """Service status information."""

    name: str
    active: str
    sub_state: str
    description: str
    main_pid: int | None
    memory: str | None
    logs: list[str]
    error: str | None


class ProcessInfo(TypedDict):
    """Process information."""

    pid: int
    user: str
    cpu: float
    mem: float
    vsz: str
    rss: str
    tty: str
    stat: str
    start: str
    time: str
    command: str


class ProcessListResponse(TypedDict, total=False):
    """Response from list_processes."""

    processes: list[ProcessInfo]
    error: str | None


# =============================================================================
# File Tool Types
# =============================================================================


class FileReadResponse(TypedDict, total=False):
    """Response from read_file."""

    content: str
    error: str | None


class FileWriteResponse(TypedDict):
    """Response from write_file."""

    success: bool
    message: str | None
    error: str | None


class DirectoryEntry(TypedDict, total=False):
    """Directory entry information."""

    name: str
    type: str  # 'file', 'directory', 'symlink', etc.
    size: int | None
    permissions: str | None
    owner: str | None
    group: str | None
    modified: str | None


class DirectoryListResponse(TypedDict, total=False):
    """Response from list_directory."""

    entries: list[DirectoryEntry]
    error: str | None


class FileSearchResponse(TypedDict, total=False):
    """Response from search_files."""

    files: list[str]
    error: str | None


# =============================================================================
# Web Tool Types
# =============================================================================


class WebSearchResult(TypedDict):
    """Individual web search result."""

    title: str
    url: str
    snippet: str


class WebSearchResponse(TypedDict, total=False):
    """Response from search_web."""

    results: list[WebSearchResult]
    query: str
    error: str | None


# =============================================================================
# Credentials Types
# =============================================================================


class CredentialsResponse(TypedDict, total=False):
    """Response from request_credentials."""

    success: bool
    service: str
    host: str | None
    fields_stored: list[str]
    reference: str
    error: str | None
    values: dict[str, str]
    stored: bool
    elevation_method: str
    next_step: str | None


# =============================================================================
# Generic Tool Response Types
# =============================================================================


class ErrorResponse(TypedDict):
    """Generic error response."""

    error: str


# Type alias for tool data that can be various types
ToolData = (
    SSHResultData
    | BashResultData
    | HostInfo
    | list[HostListItem]
    | list[PortInfo]
    | dict[str, object]
    | list[object]
    | str
    | None
)
