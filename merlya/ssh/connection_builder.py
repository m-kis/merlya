"""
Merlya SSH - Connection builder.

Handles SSH connection creation, options building, and jump host setup.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.ssh.validation import validate_private_key as _validate_private_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.ssh.types import SSHConnectionOptions


class SSHConnectionBuilder:
    """Builder for SSH connections with comprehensive options handling."""

    def __init__(
        self,
        auto_add_host_keys: bool = True,
        connect_timeout: int = 30,
        passphrase_callback: Callable[[str], str] | None = None,
    ) -> None:
        """
        Initialize connection builder.

        Args:
            auto_add_host_keys: Auto-accept unknown host keys.
            connect_timeout: Connection timeout in seconds.
            passphrase_callback: Callback for SSH key passphrases.
        """
        self.auto_add_host_keys = auto_add_host_keys
        self.connect_timeout = connect_timeout
        self._passphrase_callback = passphrase_callback

    def _get_known_hosts_path(self) -> str | None:
        """Get path to known_hosts file."""
        default_path = Path.home() / ".ssh" / "known_hosts"
        if default_path.exists():
            return str(default_path)
        # Return None to use asyncssh defaults (will prompt on new hosts)
        return None

    async def build_ssh_options(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
        host_name: str | None = None,  # Inventory name for credential lookup
        auth_manager: object | None = None,  # SSHAuthManager when available
    ) -> dict[str, Any]:
        """Build SSH connection options."""
        known_hosts = None if self.auto_add_host_keys else self._get_known_hosts_path()

        options: dict[str, Any] = {
            "host": host,
            "port": opts.port,
            "known_hosts": known_hosts,
            "agent_forwarding": True,
        }

        if username:
            options["username"] = username

        # Use auth manager if available (preferred)
        if auth_manager:
            from merlya.ssh.auth import SSHAuthManager

            if isinstance(auth_manager, SSHAuthManager):
                auth_opts = await auth_manager.prepare_auth(
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

    async def setup_jump_tunnel(self, opts: SSHConnectionOptions) -> Any | None:
        """Setup jump host tunnel if configured."""
        import asyncssh

        if not opts.jump_host:
            return None

        known_hosts = None if self.auto_add_host_keys else self._get_known_hosts_path()

        jump_options: dict[str, Any] = {
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

    async def _load_jump_key(self, key_path: Path) -> Any | None:
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

    async def _load_private_key(self, key_path: Path) -> Any:
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

    async def connect_with_options(
        self,
        host: str,
        options: dict[str, Any],
        client_factory: type | None,
        timeout: int,
    ) -> Any:
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

    async def create_connection(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
        host_name: str | None = None,
        auth_manager: object | None = None,
        mfa_client: type | None = None,
    ) -> Any:
        """Create a new SSH connection."""
        import asyncssh

        # Build connection options
        options = await self.build_ssh_options(
            host, username, private_key, opts, host_name, auth_manager
        )

        # Setup jump tunnel if needed
        tunnel: Any | None = None
        try:
            tunnel = await self.setup_jump_tunnel(opts)
            if tunnel:
                options["tunnel"] = tunnel

            # Connect with retry
            timeout_val = opts.connect_timeout or self.connect_timeout
            conn = await self.connect_with_options(host, options, mfa_client, timeout_val)

            return conn

        except (TimeoutError, asyncssh.Error) as e:
            # Clean up tunnel on connection error
            if tunnel:
                try:
                    tunnel.close()
                    await asyncio.wait_for(tunnel.wait_closed(), timeout=10.0)
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
                    tunnel.close()
                    await asyncio.wait_for(tunnel.wait_closed(), timeout=10.0)
                except (TimeoutError, Exception) as cleanup_exc:
                    logger.debug(f"⚠️ Failed to close jump tunnel: {cleanup_exc}")

            logger.error(f"❌ Unexpected error creating connection to {host}")
            raise

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
