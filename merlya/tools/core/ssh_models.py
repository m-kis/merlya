"""
Merlya Tools - SSH data models.

Type definitions and dataclasses for SSH operations.

NOTE: Elevation-related models have been removed. The LLM now handles
privilege elevation directly using sudo/doas prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from merlya.persistence.models import Host
    from merlya.ssh import SSHConnectionOptions, SSHPool


class SSHResultProtocol(Protocol):
    """Protocol for SSH execution results."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class SSHExecuteParams:
    """Parameters for SSH command execution."""

    host: str
    command: str
    timeout: int = 60
    connect_timeout: int | None = None
    via: str | None = None


@dataclass
class ExecutionContext:
    """Context for SSH command execution."""

    ssh_pool: SSHPool
    host: str
    host_entry: Host | None
    ssh_opts: SSHConnectionOptions
    timeout: int
    jump_host_name: str | None = None
    base_command: str = ""


@dataclass(frozen=True)
class SSHExecuteResult:
    """Result metadata from SSH execution."""

    host: str
    command_display: str
    jump_host_name: str | None = None
