"""
Merlya Core - Shared Context.

The SharedContext is the "socle commun" shared between all agents.
It provides access to core infrastructure: router, SSH pool, hosts,
variables, secrets, UI, and configuration.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from loguru import logger

from merlya.config import Config, get_config
from merlya.i18n import I18n, get_i18n
from merlya.secrets import SecretStore, get_secret_store

if TYPE_CHECKING:
    from merlya.health import StartupHealth
    from merlya.mcp import MCPManager
    from merlya.persistence import (
        ConversationRepository,
        Database,
        HostRepository,
        VariableRepository,
    )
    from merlya.router import IntentRouter
    from merlya.security import PermissionManager
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

    # Class-level singleton state
    _instance: ClassVar[SharedContext | None] = None
    _lock: ClassVar[asyncio.Lock]  # Initialized below

    # Core infrastructure
    config: Config
    i18n: I18n
    secrets: SecretStore
    health: StartupHealth | None = None

    # Database (initialized async)
    _db: Database | None = field(default=None, repr=False)
    _host_repo: HostRepository | None = field(default=None, repr=False)
    _var_repo: VariableRepository | None = field(default=None, repr=False)
    _conv_repo: ConversationRepository | None = field(default=None, repr=False)

    # SSH Pool (lazy init)
    _ssh_pool: SSHPool | None = field(default=None, repr=False)
    _permissions: PermissionManager | None = field(default=None, repr=False)
    _auth_manager: object | None = field(default=None, repr=False)  # SSHAuthManager

    # Intent Router (lazy init)
    _router: IntentRouter | None = field(default=None, repr=False)

    # MCP Manager
    _mcp_manager: MCPManager | None = field(default=None, repr=False)

    # Console UI
    _ui: ConsoleUI | None = field(default=None, repr=False)

    # Non-interactive mode flags
    auto_confirm: bool = field(default=False)
    quiet: bool = field(default=False)
    output_format: str = field(default="text")

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

    @property
    def conversations(self) -> ConversationRepository:
        """Get conversation repository."""
        if self._conv_repo is None:
            raise RuntimeError("Database not initialized. Call init_async() first.")
        return self._conv_repo

    async def get_ssh_pool(self) -> SSHPool:
        """Get SSH connection pool (async)."""
        if self._ssh_pool is None:
            from merlya.ssh import SSHPool

            self._ssh_pool = await SSHPool.get_instance(
                timeout=self.config.ssh.pool_timeout,
                connect_timeout=self.config.ssh.connect_timeout,
            )

            # Configure auth manager if available
            auth_manager = await self.get_auth_manager()
            if auth_manager:
                self._ssh_pool.set_auth_manager(auth_manager)

        return self._ssh_pool

    async def get_auth_manager(self) -> object | None:
        """Get SSH authentication manager (lazy)."""
        if self._auth_manager is None:
            try:
                from merlya.ssh.auth import SSHAuthManager

                self._auth_manager = SSHAuthManager(
                    secrets=self.secrets,
                    ui=self.ui,
                )
                logger.debug("SSH auth manager initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize SSH auth manager: {e}")
                return None
        return self._auth_manager

    @property
    def router(self) -> IntentRouter:
        """Get intent router."""
        if self._router is None:
            raise RuntimeError("Router not initialized. Call init_router() first.")
        return self._router

    async def get_permissions(self) -> PermissionManager:
        """Get permission manager (lazy)."""
        if self._permissions is None:
            from merlya.security import PermissionManager

            self._permissions = PermissionManager(self)
        assert self._permissions is not None
        return self._permissions

    @property
    def ui(self) -> ConsoleUI:
        """Get console UI."""
        if self._ui is None:
            from merlya.ui import ConsoleUI

            self._ui = ConsoleUI(
                auto_confirm=self.auto_confirm,
                quiet=self.quiet,
            )
        return self._ui

    async def init_async(self) -> None:
        """
        Initialize async components (database, etc).

        Must be called before using the context.
        """
        from merlya.persistence import (
            ConversationRepository,
            HostRepository,
            VariableRepository,
            get_database,
        )

        self._db = await get_database()
        self._host_repo = HostRepository(self._db)
        self._var_repo = VariableRepository(self._db)
        self._conv_repo = ConversationRepository(self._db)

        logger.debug("✅ SharedContext async components initialized")

    async def get_mcp_manager(self) -> MCPManager:
        """Get MCP manager (lazy, async-safe singleton)."""
        if self._mcp_manager is None:
            from merlya.mcp import MCPManager

            self._mcp_manager = await MCPManager.create(self.config, self.secrets)
        return self._mcp_manager

    async def init_router(self, tier: str | None = None) -> None:
        """
        Initialize intent router.

        Args:
            tier: Optional model tier (from health checks).
        """
        from merlya.router import IntentRouter

        requested_local = self.config.router.type == "local"
        use_local = requested_local

        # Disable local router if health checks flagged it as unavailable
        if self.health and requested_local:
            use_local = bool(self.health.capabilities.get("onnx_router"))

        router_model_env = os.getenv("MERLYA_ROUTER_MODEL")
        router_model_id = router_model_env or self.config.router.model

        router = IntentRouter(
            use_local=use_local,
            model_id=router_model_id,
            tier=tier,
        )

        # Configure LLM fallback for low-confidence intents
        fallback_override = os.getenv("MERLYA_ROUTER_FALLBACK")
        if fallback_override and ":" not in fallback_override:
            fallback_override = f"{self.config.model.provider}:{fallback_override}"

        fallback_value = fallback_override or self.config.router.llm_fallback
        if fallback_value:
            self.config.router.llm_fallback = fallback_value
            router.set_llm_fallback(fallback_value)

        await router.initialize()

        # Persist chosen tier for visibility
        self.config.router.tier = tier or self.config.router.tier

        if requested_local and not use_local:
            logger.warning("⚠️ ONNX router unavailable, using LLM fallback for routing")
        elif router.classifier.model_loaded:
            logger.info("✅ Intent router initialized with local ONNX model")
            # Persist selected model id for diagnostics
            if router.classifier.model_id:
                self.config.router.model = router.classifier.model_id

        self._router = router

    async def close(self) -> None:
        """Close all connections and cleanup (idempotent)."""
        # Guard against multiple close calls
        if SharedContext._instance is None:
            return

        if self._db:
            try:
                await self._db.close()
            except Exception as e:
                logger.debug(f"DB close error: {e}")
            self._db = None

        if self._ssh_pool:
            try:
                await self._ssh_pool.disconnect_all()
            except Exception as e:
                logger.debug(f"SSH pool close error: {e}")
            self._ssh_pool = None

        if self._mcp_manager:
            try:
                await self._mcp_manager.close()
            except Exception as e:
                logger.debug(f"MCP manager close error: {e}")
            self._mcp_manager = None

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


# Initialize the class-level lock
SharedContext._lock = asyncio.Lock()


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
