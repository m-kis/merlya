"""
Merlya SSH - Connection pool.

Manages SSH connections with reuse and timeout.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from asyncssh import SSHClientConnection


@dataclass
class SSHResult:
    """Result of an SSH command execution."""

    stdout: str
    stderr: str
    exit_code: int


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
        # Use timezone-aware comparison
        now = datetime.now(UTC)
        return not now - self.last_used > timedelta(seconds=self.timeout)

    def refresh_timeout(self) -> None:
        """Refresh the timeout."""
        self.last_used = datetime.now(UTC)

    async def close(self) -> None:
        """Close the connection."""
        if self.connection:
            self.connection.close()
            await self.connection.wait_closed()
            self.connection = None


class SSHPool:
    """
    SSH connection pool with reuse.

    Maintains connections for reuse and handles MFA prompts.
    Thread-safe with asyncio.Lock.
    """

    DEFAULT_TIMEOUT = 600  # 10 minutes
    DEFAULT_CONNECT_TIMEOUT = 30
    DEFAULT_MAX_CONNECTIONS = 50

    _instance: SSHPool | None = None
    _instance_lock: asyncio.Lock | None = None

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        """
        Initialize pool.

        Args:
            timeout: Connection timeout in seconds.
            connect_timeout: Initial connection timeout.
            max_connections: Maximum number of concurrent connections.
        """
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_connections = max_connections
        self._connections: dict[str, SSHConnection] = {}
        self._connection_locks: dict[str, asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()
        self._mfa_callback: Callable[[str], str] | None = None

    def set_mfa_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for MFA prompts."""
        self._mfa_callback = callback

    def _get_known_hosts_path(self) -> str | None:
        """Get path to known_hosts file."""
        default_path = Path.home() / ".ssh" / "known_hosts"
        if default_path.exists():
            return str(default_path)
        # Return None to use asyncssh defaults (will prompt on new hosts)
        return None

    async def _get_connection_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for a connection key."""
        async with self._pool_lock:
            if key not in self._connection_locks:
                self._connection_locks[key] = asyncio.Lock()
            return self._connection_locks[key]

    async def _evict_lru_connection(self) -> None:
        """Evict the least recently used connection."""
        if not self._connections:
            return

        # Find LRU connection
        lru_key = min(
            self._connections.keys(),
            key=lambda k: self._connections[k].last_used,
        )

        conn = self._connections.pop(lru_key)
        await conn.close()
        logger.debug(f"🔌 Evicted LRU connection: {lru_key}")

    async def get_connection(
        self,
        host: str,
        port: int = 22,
        username: str | None = None,
        private_key: str | None = None,
        jump_host: str | None = None,
    ) -> SSHConnection:
        """
        Get or create an SSH connection.

        Args:
            host: Target hostname or IP.
            port: SSH port.
            username: SSH username.
            private_key: Path to private key.
            jump_host: Optional jump host for tunneling.

        Returns:
            Active SSH connection.

        Raises:
            asyncio.TimeoutError: If connection times out.
            asyncssh.Error: If connection fails.
            RuntimeError: If max connections reached and eviction fails.
        """
        # Validate port number
        if not (1 <= port <= 65535):
            raise ValueError(f"Invalid port number: {port} (must be 1-65535)")

        key = f"{username or 'default'}@{host}:{port}"
        lock = await self._get_connection_lock(key)

        async with lock:
            # Check existing connection (thread-safe now)
            if key in self._connections:
                conn = self._connections[key]
                if conn.is_alive():
                    conn.refresh_timeout()
                    logger.debug(f"🔄 Reusing SSH connection to {host}")
                    return conn
                else:
                    # Clean up expired connection
                    await conn.close()
                    del self._connections[key]

            # Check pool limit
            async with self._pool_lock:
                if len(self._connections) >= self.max_connections:
                    await self._evict_lru_connection()

            # Create new connection
            conn = await self._create_connection(host, port, username, private_key, jump_host)
            self._connections[key] = conn

            logger.info(f"🌐 SSH connected to {host}")
            return conn

    async def _create_connection(
        self,
        host: str,
        port: int,
        username: str | None,
        private_key: str | None,
        jump_host: str | None,
    ) -> SSHConnection:
        """Create a new SSH connection."""
        import asyncssh

        # Get known_hosts path
        known_hosts = self._get_known_hosts_path()

        # Build connection options
        options: dict[str, object] = {
            "host": host,
            "port": port,
            "known_hosts": known_hosts,
        }

        if username:
            options["username"] = username

        if private_key:
            options["client_keys"] = [private_key]

        # Handle jump host (tunnel) with proper cleanup
        tunnel: asyncssh.SSHClientConnection | None = None
        try:
            if jump_host:
                tunnel = await asyncssh.connect(
                    jump_host,
                    known_hosts=known_hosts,
                )
                options["tunnel"] = tunnel

            # Connect with timeout
            conn = await asyncio.wait_for(
                asyncssh.connect(**options),
                timeout=self.connect_timeout,
            )

            return SSHConnection(
                host=host,
                connection=conn,
                timeout=self.timeout,
            )

        except TimeoutError:
            # Clean up tunnel on timeout
            if tunnel:
                tunnel.close()
                await tunnel.wait_closed()
            logger.error(f"❌ SSH connection timeout to {host}")
            raise

        except asyncssh.Error as e:
            # Clean up tunnel on error
            if tunnel:
                tunnel.close()
                await tunnel.wait_closed()
            logger.error(f"❌ SSH connection failed to {host}: {e}")
            raise

    async def execute(
        self,
        host: str,
        command: str,
        timeout: int = 60,
        **conn_kwargs: object,
    ) -> SSHResult:
        """
        Execute a command on a host.

        Args:
            host: Target host.
            command: Command to execute.
            timeout: Command timeout.
            **conn_kwargs: Connection options.

        Returns:
            SSHResult with stdout, stderr, and exit_code.

        Raises:
            ValueError: If host or command is empty.
        """
        # Validate inputs
        if not host or not host.strip():
            raise ValueError("Host cannot be empty")
        if not command or not command.strip():
            raise ValueError("Command cannot be empty")

        conn = await self.get_connection(host, **conn_kwargs)

        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        try:
            result = await asyncio.wait_for(
                conn.connection.run(command),
                timeout=timeout,
            )

            # Security: Never log command content (may contain secrets)
            logger.debug(
                f"⚡ Executed command on {host} (length: {len(command)} chars, exit: {result.exit_status})"
            )

            # Ensure strings (asyncssh may return bytes)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")

            return SSHResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=result.exit_status or 0,
            )

        except TimeoutError:
            logger.warning(f"⚠️ Command timeout on {host}")
            raise

    async def disconnect(self, host: str) -> None:
        """Disconnect from a specific host."""
        async with self._pool_lock:
            # Find matching connections
            to_remove = [k for k in self._connections if host in k]

            for key in to_remove:
                conn = self._connections.pop(key)
                await conn.close()
                logger.debug(f"🔌 Disconnected from {host}")

    async def disconnect_all(self) -> None:
        """Disconnect all connections."""
        async with self._pool_lock:
            for conn in self._connections.values():
                await conn.close()

            count = len(self._connections)
            self._connections.clear()
            self._connection_locks.clear()

            if count:
                logger.debug(f"🔌 Disconnected {count} SSH connection(s)")

    @classmethod
    async def get_instance(
        cls,
        timeout: int = DEFAULT_TIMEOUT,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
    ) -> SSHPool:
        """Get singleton instance (thread-safe)."""
        if cls._instance_lock is None:
            cls._instance_lock = asyncio.Lock()

        async with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(timeout, connect_timeout, max_connections)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None
        cls._instance_lock = None
