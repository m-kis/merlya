"""
Merlya Agent Specialists - Type definitions.

TypedDict definitions for specialist agent return types (no Any).
"""

from __future__ import annotations

from typing import TypedDict


class _SSHResultRequired(TypedDict):
    """Required fields for SSH result."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int


class SSHResult(_SSHResultRequired, total=False):
    """Result from SSH command execution.

    Required fields: success, stdout, stderr, exit_code
    Optional fields: hint, error
    """

    hint: str | None  # Optional hint for permission denied
    error: str | None  # Optional error message


class _ScanResultRequired(TypedDict):
    """Required fields for scan result."""

    success: bool


class ScanResult(_ScanResultRequired, total=False):
    """Result from security scan."""

    message: str
    data: dict[str, object]
    error: str


class HostInfo(TypedDict, total=False):
    """Host information from inventory."""

    id: str
    name: str
    address: str
    port: int
    user: str
    tags: list[str]
    jump_host: str
    elevation_method: str


class _HostListResultRequired(TypedDict):
    """Required fields for host list result."""

    hosts: list[HostInfo]
    count: int


class HostListResult(_HostListResultRequired, total=False):
    """Result from list_hosts."""

    error: str


class _FileReadResultRequired(TypedDict):
    """Required fields for file read result."""

    success: bool
    content: str


class FileReadResult(_FileReadResultRequired, total=False):
    """Result from read_file."""

    error: str
