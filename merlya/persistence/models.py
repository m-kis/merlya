"""
Merlya Persistence - Data models.

Pydantic models for database entities.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Import directly from types to avoid circular import through core.__init__
from merlya.core.types import HostStatus


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
