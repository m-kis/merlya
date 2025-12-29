"""
Merlya Capabilities - Pydantic Models.

Defines capability structures for hosts and tools.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ToolName(str, Enum):
    """Supported infrastructure tools."""

    ANSIBLE = "ansible"
    TERRAFORM = "terraform"
    KUBECTL = "kubectl"
    GIT = "git"
    DOCKER = "docker"
    HELM = "helm"


class SSHCapability(BaseModel):
    """SSH access capability for a host."""

    available: bool = False
    read_only: bool = False
    connection_error: str | None = None

    # Authentication details (detected, not configured)
    auth_method: Literal["key", "password", "agent", "unknown"] = "unknown"


class ToolCapability(BaseModel):
    """Capability status for a specific tool."""

    name: ToolName
    installed: bool = False
    version: str | None = None
    config_valid: bool = False
    config_error: str | None = None

    def __str__(self) -> str:
        if not self.installed:
            return f"{self.name.value}: not installed"
        status = "valid" if self.config_valid else "invalid config"
        version_str = f" v{self.version}" if self.version else ""
        return f"{self.name.value}{version_str}: {status}"


class HostCapabilities(BaseModel):
    """Complete capability profile for a host."""

    host_name: str
    ssh: SSHCapability = Field(default_factory=SSHCapability)
    tools: list[ToolCapability] = Field(default_factory=list)
    web_access: bool = False

    # Cache metadata
    cached_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = 86400  # 24 hours default

    def has_tool(self, name: ToolName | str) -> bool:
        """Check if a tool is installed and configured."""
        if isinstance(name, str):
            try:
                name = ToolName(name)
            except ValueError:
                return False
        return any(t.name == name and t.installed and t.config_valid for t in self.tools)

    def get_tool(self, name: ToolName | str) -> ToolCapability | None:
        """Get tool capability by name."""
        if isinstance(name, str):
            try:
                name = ToolName(name)
            except ValueError:
                return None
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def is_expired(self) -> bool:
        """Check if cached capabilities have expired."""
        now = datetime.now(UTC)
        # Handle both naive and aware datetimes
        if self.cached_at.tzinfo is None:
            cached = self.cached_at.replace(tzinfo=UTC)
        else:
            cached = self.cached_at
        age = (now - cached).total_seconds()
        return age > self.ttl_seconds

    @property
    def has_iac_repo(self) -> bool:
        """Check if host has any IaC tool configured (Ansible, Terraform)."""
        return self.has_tool(ToolName.ANSIBLE) or self.has_tool(ToolName.TERRAFORM)


class LocalCapabilities(BaseModel):
    """Local machine capabilities (where Merlya runs)."""

    tools: list[ToolCapability] = Field(default_factory=list)
    web_access: bool = True
    cached_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = 3600  # 1 hour for local

    def has_tool(self, name: ToolName | str) -> bool:
        """Check if a tool is installed locally."""
        if isinstance(name, str):
            try:
                name = ToolName(name)
            except ValueError:
                return False
        return any(t.name == name and t.installed for t in self.tools)

    def is_expired(self) -> bool:
        """Check if cached capabilities have expired."""
        now = datetime.now(UTC)
        # Handle both naive and aware datetimes
        if self.cached_at.tzinfo is None:
            cached = self.cached_at.replace(tzinfo=UTC)
        else:
            cached = self.cached_at
        age = (now - cached).total_seconds()
        return age > self.ttl_seconds
