"""
Merlya SSH - Connection pool.

Manages SSH connections with reuse, retry, and circuit breaker.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from merlya.ssh.sftp import SFTPOperations
from merlya.ssh.types import (
    CircuitBreaker,
    SSHConnection,
    SSHConnectionOptions,
    SSHResult,
    is_transient_error,
)
from merlya.ssh.validation import validate_private_key as _validate_private_key

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Re-export types for backwards compatibility
__all__ = ["SSHConnection", "SSHConnectionOptions", "SSHPool", "SSHResult"]


class SSHPool(SFTPOperations):
    """
    SSH connection pool with reuse, retry, and circuit breaker.

    Maintains connections for reuse and handles MFA prompts.
    Thread-safe singleton with threading.Lock for instance creation,
    asyncio.Lock for connection pool operations.

    Features:
    - Connection reuse with timeout management
    - Circuit breaker per host (prevents cascade failures)
    - Automatic retry for transient errors
    - Health checks for zombie connection detection
    """

    DEFAULT_TIMEOUT = 600  # 10 minutes
    DEFAULT_CONNECT_TIMEOUT = 30
    DEFAULT_MAX_CONNECTIONS = 50
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 1.0  # seconds

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
    ) -> None:
        """
        Initialize pool.

        Args:
            timeout: Connection timeout in seconds.
            connect_timeout: Initial connection timeout.
            max_connections: Maximum number of concurrent connections.
            auto_add_host_keys: Auto-accept unknown host keys.
            max_retries: Maximum retry attempts for transient errors.
            retry_delay: Delay between retries in seconds.
        """
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_connections = max_connections
        self.auto_add_host_keys = auto_add_host_keys
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._connections: dict[str, SSHConnection] = {}
        self._connection_locks: dict[str, asyncio.Lock] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._pool_lock = asyncio.Lock()
        self._mfa_callback: Callable[[str], str] | None = None
        self._passphrase_callback: Callable[[str], str] | None = None
        self._auth_manager: object | None = None  # SSHAuthManager when set

    def set_mfa_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for MFA prompts."""
        self._mfa_callback = callback

    def set_passphrase_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for SSH key passphrase prompts."""
        self._passphrase_callback = callback

    def has_mfa_callback(self) -> bool:
        """Check if MFA callback is configured."""
        return self._mfa_callback is not None

    def has_passphrase_callback(self) -> bool:
        """Check if passphrase callback is configured."""
        return self._passphrase_callback is not None

    def set_auth_manager(self, manager: object) -> None:
        """Set the SSH authentication manager."""
        self._auth_manager = manager

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

    def _get_circuit_breaker(self, host: str) -> CircuitBreaker:
        """Get or create circuit breaker for a host."""
        if host not in self._circuit_breakers:
            self._circuit_breakers[host] = CircuitBreaker()
        return self._circuit_breakers[host]

    def get_circuit_status(self, host: str) -> dict:
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
        username: str | None = None,
        private_key: str | None = None,
        options: SSHConnectionOptions | None = None,
        host_name: str | None = None,  # Inventory name for credential lookup
    ) -> SSHConnection:
        """
        Get or create an SSH connection.

        Args:
            host: Target hostname or IP.
            username: SSH username.
            private_key: Path to private key.
            options: Additional connection options (port, jump host, etc.).

        Returns:
            Active SSH connection.

        Raises:
            asyncio.TimeoutError: If connection times out.
            asyncssh.Error: If connection fails.
            RuntimeError: If max connections reached and eviction fails.
        """
        opts = options or SSHConnectionOptions()

        # Validate port number
        if not (1 <= opts.port <= 65535):
            raise ValueError(f"Invalid port number: {opts.port} (must be 1-65535)")

        key = f"{username or 'default'}@{host}:{opts.port}"
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
            conn = await self._create_connection(host, username, private_key, opts, host_name)
            self._connections[key] = conn

            logger.info(f"🌐 SSH connected to {host}")
            return conn

    async def _build_ssh_options(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
        host_name: str | None = None,  # Inventory name for credential lookup
    ) -> dict[str, object]:
        """Build SSH connection options."""
        known_hosts = None if self.auto_add_host_keys else self._get_known_hosts_path()

        options: dict[str, object] = {
            "host": host,
            "port": opts.port,
            "known_hosts": known_hosts,
            "agent_forwarding": True,
        }

        if username:
            options["username"] = username

        # Use auth manager if available (preferred)
        if self._auth_manager:
            from merlya.ssh.auth import SSHAuthManager

            if isinstance(self._auth_manager, SSHAuthManager):
                auth_opts = await self._auth_manager.prepare_auth(
                    hostname=host,
                    username=username,
                    private_key=private_key,
                    host_name=host_name,
                )
                options["preferred_auth"] = auth_opts.preferred_auth

                if auth_opts.client_keys:
                    options["client_keys"] = auth_opts.client_keys
                if auth_opts.password:
                    options["password"] = auth_opts.password
                if auth_opts.agent_path:
                    options["agent_path"] = auth_opts.agent_path

                logger.debug(f"Auth prepared via SSHAuthManager: {auth_opts.preferred_auth}")
                return options

        # Fallback: original behavior when no auth manager
        options["preferred_auth"] = "publickey,keyboard-interactive"

        if private_key:
            key_path = Path(private_key).expanduser()
            import os

            agent_available = os.environ.get("SSH_AUTH_SOCK") is not None

            if agent_available:
                logger.info("SSH agent available, using agent for authentication")
            elif key_path.exists():
                try:
                    key = await self._load_private_key(key_path)
                    options["client_keys"] = [key]
                    logger.debug(f"Private key loaded: {private_key}")
                except Exception as e:
                    logger.warning(f"Failed to load private key {private_key}: {e}")
            else:
                logger.warning(f"Private key not found: {private_key}")

        return options

    async def _setup_jump_tunnel(self, opts: SSHConnectionOptions) -> object | None:
        """Setup jump host tunnel if configured."""
        import asyncssh

        if not opts.jump_host:
            return None

        known_hosts = None if self.auto_add_host_keys else self._get_known_hosts_path()

        jump_options: dict[str, object] = {
            "host": opts.jump_host,
            "port": opts.jump_port or 22,
            "known_hosts": known_hosts,
            "agent_forwarding": True,
        }

        if opts.jump_username:
            jump_options["username"] = opts.jump_username

        if opts.jump_private_key:
            jump_key_path = Path(opts.jump_private_key).expanduser()
            if jump_key_path.exists():
                jump_key = await self._load_jump_key(jump_key_path)
                if jump_key:
                    jump_options["client_keys"] = [jump_key]

        return await asyncssh.connect(**jump_options)

    async def _load_jump_key(self, key_path: Path) -> object | None:
        """Load jump host private key with passphrase handling."""
        import asyncssh

        try:
            return asyncssh.read_private_key(str(key_path))
        except asyncssh.KeyEncryptionError:
            if self._passphrase_callback:
                passphrase = self._passphrase_callback(str(key_path))
                if passphrase:
                    return asyncssh.read_private_key(str(key_path), passphrase)
            logger.warning(f"⚠️ Jump key {key_path} requires passphrase - using agent")
            return None

    def _create_mfa_client(self) -> type | None:
        """Create MFA client factory if callback is set."""
        if not self._mfa_callback:
            return None

        import asyncssh

        mfa_cb = self._mfa_callback

        class _MFAClient(asyncssh.SSHClient):
            def kbdint_auth_requested(self) -> str:
                """Return empty string to let server pick keyboard-interactive method."""
                logger.debug("🔐 Keyboard-interactive auth requested")
                return ""

            def kbdint_challenge_received(
                self,
                name: str,
                instructions: str,
                _lang: str,  # Required by interface
                prompts: Sequence[tuple[str, bool]],
            ) -> list[str] | None:
                """Handle keyboard-interactive (MFA/2FA) challenges."""
                logger.debug(f"🔐 MFA challenge received: {name or 'Authentication'}")
                if instructions:
                    logger.debug(f"   Instructions: {instructions}")
                responses: list[str] = []
                for prompt, _echo in prompts:
                    response = mfa_cb(prompt)
                    responses.append(response)
                return responses

        return _MFAClient

    async def _connect_with_options(
        self,
        host: str,
        options: dict[str, object],
        client_factory: type | None,
        timeout: int,
    ) -> object:
        """Connect with retry on permission denied."""
        import asyncssh

        logger.debug(f"Connecting to {host} with auth={options.get('preferred_auth')}")

        # Remove internal hint keys before passing to asyncssh
        connect_opts = {k: v for k, v in options.items() if not k.startswith("_")}

        try:
            return await asyncio.wait_for(
                asyncssh.connect(**connect_opts, client_factory=client_factory),
                timeout=timeout,
            )
        except asyncssh.PermissionDenied as e:
            error_msg = str(e).lower()
            logger.warning(f"Permission denied: {e}")

            # If MFA/keyboard-interactive failed, don't retry - the issue isn't the key
            if "keyboard" in error_msg or "interactive" in error_msg:
                logger.error(f"❌ MFA/2FA authentication failed for {host}")
                raise

            # Only retry with agent if we had explicit keys and it looks like a key issue
            if "client_keys" in connect_opts:
                logger.warning(
                    f"⚠️ Permission denied with provided key for {host}, retrying with agent"
                )
                retry_opts = {k: v for k, v in connect_opts.items() if k != "client_keys"}
                return await asyncio.wait_for(
                    asyncssh.connect(**retry_opts, client_factory=client_factory),
                    timeout=timeout,
                )
            raise

    async def _create_connection(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
        host_name: str | None = None,  # Inventory name for credential lookup
    ) -> SSHConnection:
        """Create a new SSH connection."""
        import asyncssh

        # Build connection options
        options = await self._build_ssh_options(host, username, private_key, opts, host_name)

        # Setup jump tunnel if needed
        tunnel: object | None = None
        try:
            tunnel = await self._setup_jump_tunnel(opts)
            if tunnel:
                options["tunnel"] = tunnel

            # Setup MFA client if configured
            client_factory = self._create_mfa_client()

            # Connect with retry
            timeout_val = opts.connect_timeout or self.connect_timeout
            conn = await self._connect_with_options(host, options, client_factory, timeout_val)

            return SSHConnection(
                host=host,
                connection=conn,  # type: ignore[arg-type]
                timeout=self.timeout,
            )

        except (TimeoutError, asyncssh.Error) as e:
            # Clean up tunnel on connection error
            if tunnel:
                try:
                    tunnel.close()  # type: ignore[attr-defined]
                    await asyncio.wait_for(tunnel.wait_closed(), timeout=10.0)  # type: ignore[attr-defined]
                except (TimeoutError, Exception) as cleanup_exc:
                    logger.debug(f"⚠️ Failed to close jump tunnel: {cleanup_exc}")

            error_msg = (
                "SSH connection timeout"
                if isinstance(e, TimeoutError)
                else f"SSH connection failed: {e}"
            )
            logger.error(f"❌ {error_msg} to {host}")
            raise
        except Exception:
            # Clean up tunnel on any unexpected error
            if tunnel:
                try:
                    tunnel.close()  # type: ignore[attr-defined]
                    await asyncio.wait_for(tunnel.wait_closed(), timeout=10.0)  # type: ignore[attr-defined]
                except (TimeoutError, Exception) as cleanup_exc:
                    logger.debug(f"⚠️ Failed to close jump tunnel: {cleanup_exc}")

            logger.error(f"❌ Unexpected error creating connection to {host}")
            raise

    def has_connection(
        self, host: str, port: int | None = None, username: str | None = None
    ) -> bool:
        """
        Check if an active connection exists for the target.

        Args:
            host: Hostname or IP.
            port: Optional port (defaults to any).
            username: Optional username (defaults to any).
        """
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

    async def execute(
        self,
        host: str,
        command: str,
        timeout: int = 60,
        input_data: str | None = None,
        username: str | None = None,
        private_key: str | None = None,
        options: SSHConnectionOptions | None = None,
        host_name: str | None = None,  # Inventory name for credential lookup
        retry: bool = True,  # Enable automatic retry for transient errors
    ) -> SSHResult:
        """
        Execute a command on a host with retry and circuit breaker.

        Args:
            host: Target host.
            command: Command to execute.
            timeout: Command timeout.
            input_data: Optional stdin data.
            username: SSH username.
            private_key: Path to private key.
            options: Additional connection options (port, jump host, etc.).
            host_name: Inventory name for credential lookup.
            retry: Enable automatic retry for transient errors.

        Returns:
            SSHResult with stdout, stderr, and exit_code.

        Raises:
            ValueError: If host or command is empty.
            RuntimeError: If circuit breaker is open.
        """
        # Validate inputs
        if not host or not host.strip():
            raise ValueError("Host cannot be empty")
        if not command or not command.strip():
            raise ValueError("Command cannot be empty")

        # Check circuit breaker
        circuit = self._get_circuit_breaker(host)
        if not circuit.can_execute():
            retry_in = circuit.time_until_retry()
            raise RuntimeError(
                f"🔌 Circuit breaker open for {host}. "
                f"Too many failures. Retry in {retry_in}s or use reset_circuit()"
            )

        max_attempts = self.max_retries if retry else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                result = await self._execute_once(
                    host, command, timeout, input_data, username, private_key, options, host_name
                )

                # Success - update circuit breaker
                circuit.record_success()
                return result

            except Exception as e:
                last_error = e

                # Check if this is a transient error worth retrying
                if retry and is_transient_error(e) and attempt < max_attempts - 1:
                    logger.warning(
                        f"⚠️ Transient error on {host} (attempt {attempt + 1}/{max_attempts}): {e}"
                    )

                    # Invalidate the connection for retry
                    await self._invalidate_connection(host, username, options)

                    # Wait before retry with exponential backoff
                    delay = self.retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

                # Non-transient error or last attempt - record failure
                circuit.record_failure()
                raise

        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise RuntimeError(f"Unexpected error executing command on {host}")

    async def _execute_once(
        self,
        host: str,
        command: str,
        timeout: int,
        input_data: str | None,
        username: str | None,
        private_key: str | None,
        options: SSHConnectionOptions | None,
        host_name: str | None,
    ) -> SSHResult:
        """Execute a command once (no retry)."""
        conn = await self.get_connection(host, username, private_key, options, host_name)

        if conn.connection is None:
            raise RuntimeError(f"Connection to {host} is closed")

        try:
            result = await asyncio.wait_for(
                conn.connection.run(command, input=input_data),
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
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(timeout, connect_timeout, max_connections)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None

    # =========================================================================
    # Key Validation
    # =========================================================================

    @staticmethod
    async def validate_private_key(
        key_path: str | Path,
        passphrase: str | None = None,
    ) -> tuple[bool, str]:
        """
        Validate that a private key can be loaded (with passphrase if needed).

        Args:
            key_path: Path to private key file.
            passphrase: Optional passphrase for encrypted keys.

        Returns:
            Tuple of (success, message).
        """
        return await _validate_private_key(key_path, passphrase)

    # =========================================================================
    # MFA/2FA Support
    # =========================================================================

    async def _load_private_key(self, key_path: Path) -> object:
        """Load a private key, invoking passphrase callback on encryption errors."""
        import asyncssh

        try:
            if self._passphrase_callback:
                try:
                    key = asyncssh.read_private_key(str(key_path))
                    logger.debug(f"Key loaded without passphrase: {key_path}")
                    return key
                except (asyncssh.KeyEncryptionError, asyncssh.KeyImportError):
                    logger.debug(f"Key encrypted, requesting passphrase: {key_path}")
                    passphrase = self._passphrase_callback(str(key_path))
                    if passphrase:
                        key = asyncssh.read_private_key(str(key_path), passphrase)
                        logger.debug(f"Encrypted key loaded: {key_path}")
                        return key
                    raise asyncssh.KeyEncryptionError(
                        "Passphrase required but not provided"
                    ) from None
            else:
                return asyncssh.read_private_key(str(key_path))
        except asyncssh.KeyImportError as exc:
            logger.warning(f"Key import failed for {key_path}: {exc}")
            raise
        except asyncssh.KeyEncryptionError:
            logger.warning(f"Key {key_path} is encrypted but no passphrase provided")
            raise
