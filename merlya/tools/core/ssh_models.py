"""
Merlya Tools - SSH data models.

Type definitions and dataclasses for SSH operations.
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


@dataclass
class _DummyFailedResult:
    """Dummy result for forced elevation (skips initial attempt)."""

    stdout: str = ""
    stderr: str = "forced_elevation"
    exit_code: int = 1


@dataclass(frozen=True)
class SSHExecuteParams:
    """Parameters for SSH command execution."""

    host: str
    command: str
    timeout: int = 60
    connect_timeout: int | None = None
    via: str | None = None
    auto_elevate: bool = True


@dataclass(frozen=True)
class ElevationPayload:
    """Elevation data from request_elevation tool."""

    command: str
    base_command: str
    method: str | None = None
    input_ref: str | None = None
    # Deprecated - for backwards compatibility only
    input: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ElevationPayload | None:
        """Create from dictionary, returns None if data is empty."""
        if not data:
            return None

        def _get_str(key: str, default: str = "") -> str:
            value = data.get(key)
            return value if isinstance(value, str) else default

        def _get_opt_str(key: str) -> str | None:
            value = data.get(key)
            return value if isinstance(value, str) else None

        return cls(
            command=_get_str("command", ""),
            base_command=_get_str("base_command", ""),
            method=_get_opt_str("method"),
            input_ref=_get_opt_str("input_ref"),
            input=_get_opt_str("input"),
        )


@dataclass
class ExecutionContext:
    """Context for SSH command execution."""

    ssh_pool: SSHPool
    host: str
    host_entry: Host | None
    ssh_opts: SSHConnectionOptions
    timeout: int
    jump_host_name: str | None = None

    # Elevation state
    input_data: str | None = None
    elevation_method: str | None = None
    base_command: str = ""


@dataclass
class ElevationContext:
    """Context for elevation operations."""

    host: str
    base_command: str
    method: str
    stderr: str = ""


@dataclass(frozen=True)
class SSHExecuteResult:
    """Result metadata from SSH execution."""

    host: str
    command_display: str
    elevation_used: str | None = None
    jump_host_name: str | None = None
