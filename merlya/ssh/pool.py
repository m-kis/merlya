"""
Merlya SSH - Connection pool.

Manages SSH connections with reuse, retry, and circuit breaker.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from merlya.ssh.circuit_breaker import CircuitBreaker
from merlya.ssh.connection_builder import SSHConnectionBuilder
from merlya.ssh.executor import ExecuteParams, execute_command
from merlya.ssh.mfa_auth import MFAAuthHandler
from merlya.ssh.pool_connect_mixin import SSHPoolConnectMixin
from merlya.ssh.sftp import SFTPOperations
from merlya.ssh.types import (
    SSHConnection,
    SSHConnectionOptions,
    SSHResult,
    is_transient_error,
)
from merlya.ssh.validation import validate_private_key as _validate_private_key

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from asyncssh import SSHClientConnection


# Re-export types for backwards compatibility
from merlya.ssh.prompt_detection import PASSWORD_PROMPT_PATTERNS

__all__ = [
    "PASSWORD_PROMPT_PATTERNS",
    "SSHConnection",
    "SSHConnectionOptions",
    "SSHPool",
    "SSHResult",
]


@dataclass
class PoolConfig:
    """Configuration for SSH connection pool.

    Groups configuration to respect the 4-parameter limit.
    """

    timeout: int = 600  # 10 minutes
    connect_timeout: int = 30
    max_connections: int = 50
    max_retries: int = 3
    retry_delay: float = 1.0
    auto_add_host_keys: bool = True
    very_verbose_debug: bool = False
    max_channels_per_host: int = 4


class SSHPool(SSHPoolConnectMixin, SFTPOperations):
    """SSH connection pool with reuse, retry, and circuit breaker.

    Maintains connections for reuse and handles MFA prompts.
    Thread-safe singleton with threading.Lock for instance creation,
    asyncio.Lock for connection pool operations.

    Features:
    - Connection reuse with timeout management
    - Circuit breaker per host (prevents cascade failures)
    - Automatic retry for transient errors
    - Health checks for zombie connection detection
    """

    DEFAULT_TIMEOUT = 600
    DEFAULT_CONNECT_TIMEOUT = 30
    DEFAULT_MAX_CONNECTIONS = 50
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 1.0
    DEFAULT_MAX_CHANNELS_PER_HOST = 4

    _instance: SSHPool | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        auto_add_host_keys: bool = True,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        very_verbose_debug: bool = False,
    ) -> None:
        """Initialize pool with configuration."""
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_connections = max_connections
        self.auto_add_host_keys = auto_add_host_keys
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.very_verbose_debug = very_verbose_debug

        # Internal state
        self._connections: dict[str, SSHConnection] = {}
        self._connection_locks: dict[str, asyncio.Lock] = {}
        self._host_run_semaphores: dict[str, asyncio.Semaphore] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._pool_lock = asyncio.Lock()
        self._max_channels_per_host = SSHPool.DEFAULT_MAX_CHANNELS_PER_HOST

        # Modular components
        self._builder = SSHConnectionBuilder(
            auto_add_host_keys=auto_add_host_keys,
            connect_timeout=connect_timeout,
        )
        self._mfa_handler = MFAAuthHandler()

        # Callbacks
        self._mfa_callback: Callable[[str], str] | None = None
        self._passphrase_callback: Callable[[str], str] | None = None
        self._auth_manager: object | None = None

    # =========================================================================
    # Callback setters
    # =========================================================================

    def set_mfa_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for MFA prompts."""
        self._mfa_callback = callback
        self._mfa_handler._mfa_callback = callback

    def set_passphrase_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for SSH key passphrase prompts."""
        self._passphrase_callback = callback
        self._mfa_handler._passphrase_callback = callback
        self._builder._passphrase_callback = callback

    def has_mfa_callback(self) -> bool:
        """Check if MFA callback is configured."""
        return self._mfa_callback is not None

    def has_passphrase_callback(self) -> bool:
        """Check if passphrase callback is configured."""
        return self._passphrase_callback is not None

    def set_auth_manager(self, manager: object) -> None:
        """Set the SSH authentication manager."""
        self._auth_manager = manager

    # =========================================================================
    # Lock management
    # =========================================================================

    async def _get_connection_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for a connection key."""
        async with self._pool_lock:
            if key not in self._connection_locks:
                self._connection_locks[key] = asyncio.Lock()
            return self._connection_locks[key]

    async def _get_host_run_semaphore(self, key: str) -> asyncio.Semaphore:
        """Get or create a per-host semaphore to limit concurrent channels."""
        async with self._pool_lock:
            if key not in self._host_run_semaphores:
                self._host_run_semaphores[key] = asyncio.Semaphore(self._max_channels_per_host)
            return self._host_run_semaphores[key]

    def _host_run_key(self, host: str, options: SSHConnectionOptions | None) -> str:
        """Build a stable key for per-host channel throttling."""
        port = options.port if options else 22
        return f"{host}:{port}"

    # =========================================================================
    # Circuit breaker
    # =========================================================================

    def _get_circuit_breaker(self, host: str) -> CircuitBreaker:
        """Get or create circuit breaker for a host."""
        if host not in self._circuit_breakers:
            self._circuit_breakers[host] = CircuitBreaker()
        return self._circuit_breakers[host]

    def get_circuit_status(self, host: str) -> dict[str, str | int | float]:
        """Get circuit breaker status for a host."""
        cb = self._get_circuit_breaker(host)
        return {
            "host": host,
            "state": cb.state.value,
            "failure_count": cb.failure_count,
            "time_until_retry": cb.time_until_retry(),
        }

    def reset_circuit(self, host: str) -> None:
        """Reset circuit breaker for a host (manual recovery)."""
        if host in self._circuit_breakers:
            self._circuit_breakers[host] = CircuitBreaker()
            logger.info(f"🔌 Circuit breaker reset for {host}")

    # =========================================================================
    # Connection management
    # =========================================================================

    async def _evict_lru_connection(self) -> None:
        """Evict the least recently used connection."""
        if not self._connections:
            return

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
        username: str | None = None,
        private_key: str | None = None,
        options: SSHConnectionOptions | None = None,
        host_name: str | None = None,
    ) -> SSHConnection:
        """Get or create an SSH connection."""
        opts = options or SSHConnectionOptions()

        if not (1 <= opts.port <= 65535):
            raise ValueError(f"Invalid port number: {opts.port} (must be 1-65535)")

        key = f"{username or 'default'}@{host}:{opts.port}"
        lock = await self._get_connection_lock(key)

        async with lock:
            if key in self._connections:
                conn = self._connections[key]
                if conn.is_alive():
                    conn.refresh_timeout()
                    logger.debug(f"🔄 Reusing SSH connection to {host}")
                    return conn
                else:
                    await conn.close()
                    del self._connections[key]

            async with self._pool_lock:
                if len(self._connections) >= self.max_connections:
                    await self._evict_lru_connection()

            conn = await self._create_connection(host, username, private_key, opts, host_name)
            self._connections[key] = conn

            logger.info(f"🌐 SSH connected to {host}")
            return conn

    async def _create_connection(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
        host_name: str | None = None,
    ) -> SSHConnection:
        """Create a new SSH connection."""
        tunnel: SSHClientConnection | None = None
        try:
            options = await self._build_ssh_options(host, username, private_key, opts, host_name)

            tunnel = await self._setup_jump_tunnel(opts)
            if tunnel:
                options["tunnel"] = tunnel

            client_factory = self._create_mfa_client()
            timeout_val = opts.connect_timeout or self.connect_timeout
            ssh_conn = await self._connect_with_options(host, options, client_factory, timeout_val)

            return SSHConnection(
                host=host,
                connection=ssh_conn,
                timeout=self.timeout,
            )
        except Exception:
            if tunnel:
                with contextlib.suppress(Exception):
                    tunnel.close()
                with contextlib.suppress(Exception):
                    wait_closed = getattr(tunnel, "wait_closed", None)
                    if callable(wait_closed):
                        await wait_closed()
            raise

    def has_connection(
        self, host: str, port: int | None = None, username: str | None = None
    ) -> bool:
        """Check if an active connection exists for the target."""
        for key, conn in self._connections.items():
            if not conn.is_alive():
                continue
            user_part, rest = key.split("@", 1)
            host_part, port_part = rest.split(":", 1)
            host_matches = host_part == host or conn.host == host
            port_matches = port is None or int(port_part) == port
            user_matches = username is None or user_part == (username or "default")
            if host_matches and port_matches and user_matches:
                return True
        return False

    # =========================================================================
    # Command execution
    # =========================================================================

    async def execute(
        self,
        host: str,
        command: str,
        timeout: int = 60,
        input_data: str | None = None,
        username: str | None = None,
        private_key: str | None = None,
        options: SSHConnectionOptions | None = None,
        host_name: str | None = None,
        retry: bool = True,
    ) -> SSHResult:
        """Execute a command on a host with retry and circuit breaker."""
        if not host or not host.strip():
            raise ValueError("Host cannot be empty")
        if not command or not command.strip():
            raise ValueError("Command cannot be empty")

        circuit = self._get_circuit_breaker(host)
        if not circuit.can_execute():
            retry_in = circuit.time_until_retry()
            raise RuntimeError(
                f"🔌 Circuit breaker open for {host}. "
                f"Too many failures. Retry in {retry_in}s or use reset_circuit()"
            )

        params = ExecuteParams(
            host=host,
            command=command,
            timeout=timeout,
            input_data=input_data,
            options=options,
            host_name=host_name,
        )

        max_attempts = self.max_retries if retry else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                return await self._execute_once(params, circuit, username, private_key)
            except Exception as e:
                last_error = e

                if retry and is_transient_error(e) and attempt < max_attempts - 1:
                    logger.warning(
                        f"⚠️ Transient error on {host} (attempt {attempt + 1}/{max_attempts}): {e}"
                    )
                    await self._invalidate_connection(host, username, options)
                    delay = self.retry_delay * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

                circuit.record_failure()
                raise

        if last_error:
            raise last_error
        raise RuntimeError(f"Unexpected error executing command on {host}")

    async def _execute_once(
        self,
        params: ExecuteParams,
        circuit: CircuitBreaker,
        username: str | None = None,
        private_key: str | None = None,
    ) -> SSHResult:
        """Execute a command once (no retry)."""
        conn = await self.get_connection(
            params.host,
            username,
            private_key,
            params.options,
            params.host_name,
        )

        run_key = self._host_run_key(params.host, params.options)
        semaphore = await self._get_host_run_semaphore(run_key)

        async with semaphore:
            result = await execute_command(params, conn, self.very_verbose_debug)

        circuit.record_success()
        return result

    async def _invalidate_connection(
        self,
        host: str,
        username: str | None,
        options: SSHConnectionOptions | None,
    ) -> None:
        """Invalidate a connection for reconnection on next attempt."""
        opts = options or SSHConnectionOptions()
        key = f"{username or 'default'}@{host}:{opts.port}"

        async with self._pool_lock:
            if key in self._connections:
                conn = self._connections.pop(key)
                conn.mark_unhealthy()
                with contextlib.suppress(Exception):
                    await conn.close()
                logger.debug(f"🔌 Invalidated connection: {key}")

    # =========================================================================
    # Disconnect methods
    # =========================================================================

    async def disconnect(self, host: str) -> None:
        """Disconnect from a specific host."""
        async with self._pool_lock:
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

    # =========================================================================
    # Singleton
    # =========================================================================

    @classmethod
    async def get_instance(
        cls,
        timeout: int = DEFAULT_TIMEOUT,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        very_verbose_debug: bool = False,
    ) -> SSHPool:
        """Get singleton instance (thread-safe)."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(
                    timeout, connect_timeout, max_connections, very_verbose_debug=very_verbose_debug
                )
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None

    # =========================================================================
    # Key validation
    # =========================================================================

    @staticmethod
    async def validate_private_key(
        key_path: str | Path,
        passphrase: str | None = None,
    ) -> tuple[bool, str]:
        """Validate that a private key can be loaded."""
        return await _validate_private_key(key_path, passphrase)
