"""
Merlya SSH - Connection pool.

Manages SSH connections with reuse and timeout.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from merlya.ssh.sftp import SFTPOperations

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


class SSHPool(SFTPOperations):
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
        auto_add_host_keys: bool = True,
    ) -> None:
        """
        Initialize pool.

        Args:
            timeout: Connection timeout in seconds.
            connect_timeout: Initial connection timeout.
            max_connections: Maximum number of concurrent connections.
            auto_add_host_keys: Auto-accept unknown host keys.
        """
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_connections = max_connections
        self.auto_add_host_keys = auto_add_host_keys
        self._connections: dict[str, SSHConnection] = {}
        self._connection_locks: dict[str, asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()
        self._mfa_callback: Callable[[str], str] | None = None
        self._passphrase_callback: Callable[[str], str] | None = None

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
        username: str | None = None,
        private_key: str | None = None,
        options: SSHConnectionOptions | None = None,
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
            conn = await self._create_connection(host, username, private_key, opts)
            self._connections[key] = conn

            logger.info(f"🌐 SSH connected to {host}")
            return conn

    async def _build_ssh_options(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
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

        # Handle private key with passphrase support
        if private_key:
            key_path = Path(private_key).expanduser()
            if key_path.exists():
                key = await self._load_private_key(key_path)
                options["client_keys"] = [key]
            else:
                logger.warning(f"⚠️ Private key not found: {private_key}")

        return options

    async def _setup_jump_tunnel(
        self, opts: SSHConnectionOptions
    ) -> object | None:
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
            def kbdint_challenge(self, name, instructions, prompts):  # type: ignore[override]
                responses: list[str] = []
                for prompt, _echo in prompts:
                    responses.append(mfa_cb(prompt))
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

        try:
            return await asyncio.wait_for(
                asyncssh.connect(**options, client_factory=client_factory),
                timeout=timeout,
            )
        except asyncssh.PermissionDenied:
            logger.warning(f"⚠️ Permission denied with provided key for {host}, retrying with agent")
            retry_opts = dict(options)
            retry_opts.pop("client_keys", None)
            return await asyncio.wait_for(
                asyncssh.connect(**retry_opts, client_factory=client_factory),
                timeout=timeout,
            )

    async def _create_connection(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
    ) -> SSHConnection:
        """Create a new SSH connection."""
        import asyncssh

        # Build connection options
        options = await self._build_ssh_options(host, username, private_key, opts)

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
            conn = await self._connect_with_options(
                host, options, client_factory, timeout_val
            )

            return SSHConnection(
                host=host,
                connection=conn,
                timeout=self.timeout,
            )

        except (TimeoutError, asyncssh.Error) as e:
            # Clean up tunnel on error
            if tunnel:
                tunnel.close()  # type: ignore[attr-defined]
                await tunnel.wait_closed()  # type: ignore[attr-defined]

            error_msg = "SSH connection timeout" if isinstance(e, TimeoutError) else f"SSH connection failed: {e}"
            logger.error(f"❌ {error_msg} to {host}")
            raise

    def has_connection(self, host: str, port: int | None = None, username: str | None = None) -> bool:
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
            if host_part == host or conn.host == host:
                if port is None or int(port_part) == port:
                    if username is None or user_part == (username or "default"):
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
    ) -> SSHResult:
        """
        Execute a command on a host.

        Args:
            host: Target host.
            command: Command to execute.
            timeout: Command timeout.
            input_data: Optional stdin data.
            username: SSH username.
            private_key: Path to private key.
            options: Additional connection options (port, jump host, etc.).

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

        conn = await self.get_connection(host, username, private_key, options)

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
        import asyncssh
        from pathlib import Path as PathlibPath

        path = PathlibPath(key_path).expanduser()

        if not path.exists():
            return False, f"Key file not found: {path}"

        # Check permissions (should be 600 or 400)
        mode = path.stat().st_mode & 0o777
        if mode not in (0o600, 0o400):
            return False, f"Key permissions too open ({oct(mode)}). Should be 600 or 400."

        try:
            # Try to read the key
            if passphrase:
                key = asyncssh.read_private_key(str(path), passphrase)
            else:
                key = asyncssh.read_private_key(str(path))

            # Get key info
            key_type = key.get_algorithm()
            key_comment = getattr(key, "comment", None) or "no comment"

            return True, f"Valid {key_type} key ({key_comment})"

        except asyncssh.KeyEncryptionError:
            return False, "Key is encrypted - passphrase required"
        except asyncssh.KeyImportError as e:
            return False, f"Invalid key format: {e}"
        except Exception as e:
            return False, f"Failed to load key: {e}"

    # =========================================================================
    # MFA/2FA Support
    # =========================================================================

    async def _load_private_key(self, key_path: Path):
        """Load a private key, invoking passphrase callback on encryption errors."""
        import asyncssh

        try:
            if self._passphrase_callback:
                try:
                    return asyncssh.read_private_key(str(key_path))
                except (asyncssh.KeyEncryptionError, asyncssh.KeyImportError):
                    passphrase = self._passphrase_callback(str(key_path))
                    if passphrase:
                        logger.debug(f"🔒 Using stored passphrase for key {key_path}")
                        return asyncssh.read_private_key(str(key_path), passphrase)
                    raise asyncssh.KeyEncryptionError("Passphrase required")
            else:
                try:
                    return asyncssh.read_private_key(str(key_path))
                except (asyncssh.KeyEncryptionError, asyncssh.KeyImportError):
                    passphrase = self._passphrase_callback(str(key_path))
                    if not passphrase:
                        raise asyncssh.KeyEncryptionError("Passphrase required")
                    return asyncssh.read_private_key(str(key_path), passphrase)
        except asyncssh.KeyImportError as exc:
            logger.warning(f"⚠️ Key import failed for {key_path}: {exc}")
            raise
        except asyncssh.KeyEncryptionError as exc:
            logger.warning(f"⚠️ Key {key_path} requires passphrase: {exc}")
            raise
