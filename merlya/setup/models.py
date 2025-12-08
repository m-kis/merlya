"""
Merlya Setup - Data models.

Models used during setup wizard and inventory import.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HostData:
    """Host data extracted from inventory sources."""

    name: str
    hostname: str | None = None
    port: int = 22
    username: str | None = None
    private_key: str | None = None
    jump_host: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
