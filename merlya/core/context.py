"""
Merlya Core - Shared Context.

The SharedContext is the "socle commun" shared between all agents.
It provides access to core infrastructure: router, SSH pool, hosts,
variables, secrets, UI, and configuration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.config import Config, get_config
from merlya.i18n import I18n, get_i18n
from merlya.secrets import SecretStore, get_secret_store

if TYPE_CHECKING:
    from merlya.health import StartupHealth
    from merlya.persistence import (  # noqa: TC004 - circular import prevention
        Database,
        HostRepository,
        VariableRepository,
    )
    from merlya.router import IntentRouter
    from merlya.ssh import SSHPool
    from merlya.ui import ConsoleUI


@dataclass
class SharedContext:
    """
    Shared context between all agents.

    This is the central infrastructure that all agents and tools
    have access to. It's initialized once at startup and passed
    to agents via dependency injection.
    """

    # Core infrastructure
    config: Config
    i18n: I18n
    secrets: SecretStore
    health: StartupHealth | None = None

    # Database (initialized async)
    _db: Database | None = field(default=None, repr=False)
    _host_repo: HostRepository | None = field(default=None, repr=False)
    _var_repo: VariableRepository | None = field(default=None, repr=False)

    # SSH Pool (lazy init)
    _ssh_pool: SSHPool | None = field(default=None, repr=False)

    # Intent Router (lazy init)
    _router: IntentRouter | None = field(default=None, repr=False)

    # Console UI
    _ui: ConsoleUI | None = field(default=None, repr=False)

    @property
    def db(self) -> Database:
        """Get database connection."""
        if self._db is None:
            raise RuntimeError("Database not initialized. Call init_async() first.")
        return self._db

    @property
    def hosts(self) -> HostRepository:
        """Get host repository."""
        if self._host_repo is None:
            raise RuntimeError("Database not initialized. Call init_async() first.")
        return self._host_repo

    @property
    def variables(self) -> VariableRepository:
        """Get variable repository."""
        if self._var_repo is None:
            raise RuntimeError("Database not initialized. Call init_async() first.")
        return self._var_repo

    async def get_ssh_pool(self) -> SSHPool:
        """Get SSH connection pool (async)."""
        if self._ssh_pool is None:
            from merlya.ssh import SSHPool

            self._ssh_pool = await SSHPool.get_instance(
                timeout=self.config.ssh.pool_timeout,
                connect_timeout=self.config.ssh.connect_timeout,
            )
        return self._ssh_pool

    @property
    def router(self) -> IntentRouter:
        """Get intent router."""
        if self._router is None:
            raise RuntimeError("Router not initialized. Call init_router() first.")
        return self._router

    @property
    def ui(self) -> ConsoleUI:
        """Get console UI."""
        if self._ui is None:
            from merlya.ui import ConsoleUI

            self._ui = ConsoleUI()
        return self._ui

    async def init_async(self) -> None:
        """
        Initialize async components (database, etc).

        Must be called before using the context.
        """
        from merlya.persistence import get_database

        self._db = await get_database()
        self._host_repo = HostRepository(self._db)
        self._var_repo = VariableRepository(self._db)

        logger.debug("✅ SharedContext async components initialized")

    async def init_router(self, tier: str | None = None) -> None:
        """
        Initialize intent router.

        Args:
            tier: Optional model tier (from health checks).
        """
        # TODO: Implement IntentRouter initialization
        logger.debug(f"🧠 Router initialization (tier: {tier or 'auto'})")

    async def close(self) -> None:
        """Close all connections and cleanup."""
        if self._db:
            await self._db.close()

        if self._ssh_pool:
            await self._ssh_pool.disconnect_all()

        # Clear singleton reference
        SharedContext._instance = None

        logger.debug("✅ SharedContext closed")

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate a key using the i18n instance."""
        return self.i18n.t(key, **kwargs)

    @classmethod
    def get_instance(cls) -> SharedContext:
        """Get singleton instance."""
        if cls._instance is None:
            raise RuntimeError("SharedContext not initialized. Call create() first.")
        return cls._instance

    @classmethod
    async def create(
        cls,
        config: Config | None = None,
        language: str | None = None,
    ) -> SharedContext:
        """
        Create and initialize a SharedContext (thread-safe).

        Args:
            config: Optional config override.
            language: Optional language override.

        Returns:
            Initialized SharedContext.
        """
        async with cls._lock:
            # Double-check pattern
            if cls._instance is not None:
                return cls._instance

            cfg = config or get_config()
            lang = language or cfg.general.language

            ctx = cls(
                config=cfg,
                i18n=get_i18n(lang),
                secrets=get_secret_store(),
            )

            await ctx.init_async()

            cls._instance = ctx
            logger.debug("✅ SharedContext created and initialized")

            return ctx

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None


# Class-level singleton state (outside dataclass fields)
SharedContext._instance: SharedContext | None = None
SharedContext._lock: asyncio.Lock = asyncio.Lock()


async def get_context() -> SharedContext:
    """
    Get or create the shared context.

    Returns:
        SharedContext singleton.
    """
    try:
        return SharedContext.get_instance()
    except RuntimeError:
        return await SharedContext.create()
