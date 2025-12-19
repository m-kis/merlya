"""
Merlya Agent Specialists - Type definitions.

TypedDict definitions for specialist agent return types (no Any).
"""

from __future__ import annotations

from typing import TypedDict


class SSHResult(TypedDict, total=False):
    """Result from SSH command execution."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    hint: str  # Optional hint for permission denied
    error: str  # Optional error message


class ScanResult(TypedDict, total=False):
    """Result from security scan."""

    success: bool
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


class HostListResult(TypedDict, total=False):
    """Result from list_hosts."""

    hosts: list[HostInfo]
    count: int
    error: str


class FileReadResult(TypedDict, total=False):
    """Result from read_file."""

    success: bool
    content: str
    error: str
