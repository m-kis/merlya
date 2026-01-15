"""
Merlya Persistence - Data models.

Pydantic models for database entities.
"""

from __future__ import annotations

import re
import socket
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Import directly from types to avoid circular import through core.__init__
from merlya.core.types import HostStatus

# Validation constants
MAX_HOSTNAME_LENGTH = 253  # RFC 1035
MIN_PORT = 1
MAX_PORT = 65535
MAX_NAME_LENGTH = 100

# Valid hostname pattern (RFC 1123)
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(\.[a-zA-Z0-9-]{1,63})*$"
)

# Valid IPv4 pattern
IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

# Valid name pattern (alphanumeric, dash, underscore, dot)
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

# Valid tag pattern (exported for reuse in hosts_formats.py)
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_:-]{1,50}$")


class ElevationMethod(str, Enum):
    """Elevation method for privilege escalation.

    Configured explicitly per host - no auto-detection.
    """

    NONE = "none"  # No elevation available/configured
    SUDO = "sudo"  # sudo with NOPASSWD configured
    SUDO_PASSWORD = "sudo_password"  # sudo requiring password
    DOAS = "doas"  # doas with NOPASSWD (BSD)
    DOAS_PASSWORD = "doas_password"  # doas requiring password
    SU = "su"  # su (requires root password)


class SSHMode(str, Enum):
    """SSH access mode for the host."""

    READ_ONLY = "read_only"  # Only read operations allowed
    READ_WRITE = "read_write"  # Full access (default)


class OSInfo(BaseModel):
    """Operating system information."""

    name: str = ""
    version: str = ""
    kernel: str = ""
    arch: str = ""
    hostname: str = ""


class Host(BaseModel):
    """Host entity."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    hostname: str
    port: int = 22
    username: str | None = None

    # SSH config
    private_key: str | None = None
    jump_host: str | None = None

    # Elevation config (explicit per-host, no auto-detection)
    elevation_method: ElevationMethod = ElevationMethod.NONE
    elevation_user: str = "root"  # Target user for elevation (default: root)
    ssh_mode: SSHMode = SSHMode.READ_WRITE  # SSH access mode

    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Enrichment
    os_info: OSInfo | None = None
    health_status: HostStatus = HostStatus.UNKNOWN
    last_seen: datetime | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate host name."""
        if not v or not v.strip():
            raise ValueError("Host name cannot be empty")
        v = v.strip()
        if len(v) > MAX_NAME_LENGTH:
            raise ValueError(f"Host name exceeds maximum length ({MAX_NAME_LENGTH} chars)")
        if not NAME_PATTERN.match(v):
            raise ValueError(
                f"Invalid host name '{v}'. "
                "Use only letters, numbers, dots, hyphens, and underscores. "
                "Must start with alphanumeric."
            )
        return v

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        """Validate hostname (IPv4, IPv6, or DNS name)."""
        if not v or not v.strip():
            raise ValueError("Hostname cannot be empty")
        v = v.strip()
        if len(v) > MAX_HOSTNAME_LENGTH:
            raise ValueError(f"Hostname exceeds maximum length ({MAX_HOSTNAME_LENGTH} chars)")
        # Allow IPv4 addresses
        if IPV4_PATTERN.match(v):
            return v
        # Allow IPv6 addresses
        try:
            socket.inet_pton(socket.AF_INET6, v)
            return v
        except OSError:
            pass
        # Validate hostname format (RFC 1123)
        if not HOSTNAME_PATTERN.match(v):
            raise ValueError(
                f"Invalid hostname '{v}'. Must be a valid IPv4/IPv6 address or RFC 1123 hostname."
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate SSH port."""
        if not MIN_PORT <= v <= MAX_PORT:
            raise ValueError(f"Port must be between {MIN_PORT} and {MAX_PORT}")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        """Validate and sanitize tags."""
        return [tag for tag in v if tag and TAG_PATTERN.match(tag)]


class Variable(BaseModel):
    """Variable entity (key-value)."""

    name: str
    value: str
    is_env: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class Conversation(BaseModel):
    """Conversation entity."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ScanCache(BaseModel):
    """Cached scan result."""

    host_id: str
    scan_type: str
    data: dict[str, Any]
    expires_at: datetime
