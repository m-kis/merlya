"""
Merlya SSH - Type definitions.

Common types used across SSH modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from asyncssh import SSHClientConnection


@dataclass
class SSHResult:
    """Result of an SSH command execution."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass
class SSHConnectionOptions:
    """SSH connection configuration options."""

    port: int = 22
    jump_host: str | None = None
    jump_port: int | None = None
    jump_username: str | None = None
    jump_private_key: str | None = None
    connect_timeout: int | None = None


@dataclass
class SSHConnection:
    """Wrapper for an SSH connection with timeout management."""

    host: str
    connection: SSHClientConnection | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    timeout: int = 600

    def is_alive(self) -> bool:
        """Check if connection is still valid."""
        if self.connection is None:
            return False
        now = datetime.now(UTC)
        return not now - self.last_used > timedelta(seconds=self.timeout)

    def refresh_timeout(self) -> None:
        """Refresh the timeout."""
        self.last_used = datetime.now(UTC)

    async def close(self) -> None:
        """Close the connection."""
        if self.connection:
            self.connection.close()
            try:
                await asyncio.wait_for(self.connection.wait_closed(), timeout=10.0)
            except TimeoutError:
                logger.warning("⚠️ Connection close timeout after 10s")
            self.connection = None
