"""
Merlya SSH - Connection helpers for SSHPool.

Extracted from `pool.py` to keep modules under the ~600 LOC guideline while
preserving backwards-compatible behavior.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.ssh.connection_builder import SSHConnectionBuilder
    from merlya.ssh.mfa_auth import MFAAuthHandler
    from merlya.ssh.types import SSHConnectionOptions


class SSHPoolConnectMixin:
    """Mixin providing connection/auth helper methods for SSHPool."""

    auto_add_host_keys: bool
    connect_timeout: int
    _builder: SSHConnectionBuilder
    _mfa_handler: MFAAuthHandler
    _mfa_callback: Callable[[str], str] | None
    _passphrase_callback: Callable[[str], str] | None
    _auth_manager: object | None

    # =========================================================================
    # Backward-compatible internal helpers (used by tests and older code)
    # =========================================================================

    def _get_known_hosts_path(self) -> str | None:
        """Get path to known_hosts file (or None if missing)."""
        return self._builder._get_known_hosts_path()

    def _create_mfa_client(self) -> type | None:
        """Create MFA client factory if callback is set."""
        self._mfa_handler._mfa_callback = self._mfa_callback
        return self._mfa_handler.create_mfa_client()

    async def _load_jump_key(self, key_path: Path) -> Any | None:
        """Load jump host key with optional passphrase handling."""
        self._builder._passphrase_callback = self._passphrase_callback
        return await self._builder._load_jump_key(key_path)

    async def _load_private_key(self, key_path: Path) -> Any:
        """Load private key with optional passphrase handling."""
        self._builder._passphrase_callback = self._passphrase_callback
        return await self._builder._load_private_key(key_path)

    async def _build_ssh_options(
        self,
        host: str,
        username: str | None,
        private_key: str | None,
        opts: SSHConnectionOptions,
        host_name: str | None = None,
    ) -> dict[str, Any]:
        """Build asyncssh.connect() options (legacy behavior)."""
        known_hosts = None if self.auto_add_host_keys else self._get_known_hosts_path()

        options: dict[str, Any] = {
            "host": host,
            "port": opts.port,
            "known_hosts": known_hosts,
            "agent_forwarding": True,
        }

        if username:
            options["username"] = username

        # Preferred: use auth manager when available.
        if self._auth_manager is not None:
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
                return options

        # Fallback: original behavior.
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

    async def _setup_jump_tunnel(self, opts: SSHConnectionOptions) -> Any | None:
        """Setup jump host tunnel if configured (legacy behavior)."""
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

    async def _connect_with_options(
        self,
        host: str,
        options: dict[str, Any],
        client_factory: type | None,
        timeout: int,
    ) -> Any:
        """Connect using asyncssh with retry handling (delegated to builder)."""
        return await self._builder.connect_with_options(host, options, client_factory, timeout)


__all__ = ["SSHPoolConnectMixin"]
