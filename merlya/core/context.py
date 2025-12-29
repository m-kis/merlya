"""
Merlya Core - Shared Context.

The SharedContext is the "socle commun" shared between all agents.
It provides access to core infrastructure: router, SSH pool, hosts,
variables, secrets, UI, and configuration.

Architecture v0.8.0: SharedContext now composes focused sub-contexts:
- ConfigContext: Configuration, i18n, secrets (immutable after init)
- DataContext: Database and repositories (thread-safe)
- ExecutionContext: SSH, elevation, MCP, router (lazy-init)
- UIContext: Console UI and user interaction
- SessionState: Transient session state with password TTL
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from loguru import logger

from merlya.config import Config, get_config
from merlya.core.contexts import (
    ConfigContext,
    DataContext,
    ExecutionContext,
    SessionState,
    UIContext,
)
from merlya.i18n import I18n, get_i18n
from merlya.secrets import SecretStore, get_secret_store
from merlya.secrets.session import SessionPasswordStore, get_session_store

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
    from merlya.security import ElevationManager
    from merlya.ssh import SSHPool
    from merlya.tools.core.user_input import AskUserCache
    from merlya.ui import ConsoleUI


@dataclass
class SharedContext:
    """
    Shared context between all agents.

    This is the central infrastructure that all agents and tools
    have access to. It's initialized once at startup and passed
    to agents via dependency injection.

    Composed of focused sub-contexts for better separation of concerns:
    - config_ctx: Configuration and settings (ConfigContext)
    - data_ctx: Database and repositories (DataContext)
    - exec_ctx: Runtime services (ExecutionContext)
    - ui_ctx: User interface (UIContext)
    - session: Session state with TTL (SessionState)
    """

    # Class-level singleton state
    _instance: ClassVar[SharedContext | None] = None
    _lock: ClassVar[asyncio.Lock]  # Initialized below

    # Core infrastructure (backward-compatible direct access)
    config: Config
    i18n: I18n
    secrets: SecretStore
    health: StartupHealth | None = None

    # Focused sub-contexts (v0.8.0 architecture)
    _config_ctx: ConfigContext | None = field(default=None, repr=False)
    _data_ctx: DataContext | None = field(default=None, repr=False)
    _exec_ctx: ExecutionContext | None = field(default=None, repr=False)
    _ui_ctx: UIContext | None = field(default=None, repr=False)
    _session: SessionState = field(default_factory=SessionState, repr=False)

    # Database (initialized async) - kept for backward compatibility
    _db: Database | None = field(default=None, repr=False)
    _host_repo: HostRepository | None = field(default=None, repr=False)
    _var_repo: VariableRepository | None = field(default=None, repr=False)
    _conv_repo: ConversationRepository | None = field(default=None, repr=False)

    # SSH Pool (lazy init)
    _ssh_pool: SSHPool | None = field(default=None, repr=False)
    _elevation: ElevationManager | None = field(default=None, repr=False)
    _auth_manager: object | None = field(default=None, repr=False)  # SSHAuthManager

    # Intent Router (lazy init)
    _router: IntentRouter | None = field(default=None, repr=False)

    # MCP Manager
    _mcp_manager: MCPManager | None = field(default=None, repr=False)

    # Console UI
    _ui: ConsoleUI | None = field(default=None, repr=False)

    # Session passwords (in-memory only, not persisted)
    _session_passwords: SessionPasswordStore | None = field(default=None, repr=False)

    # Ask user cache for input deduplication
    _ask_user_cache: AskUserCache | None = field(default=None, repr=False)

    # Non-interactive mode flags
    auto_confirm: bool = field(default=False)
    quiet: bool = field(default=False)
    output_format: str = field(default="text")

    # Sub-context property accessors (v0.8.0)
    @property
    def config_ctx(self) -> ConfigContext:
        """Get configuration context (immutable after init)."""
        if self._config_ctx is None:
            self._config_ctx = ConfigContext(
                config=self.config,
                i18n=self.i18n,
                secrets=self.secrets,
                health=self.health,
            )
        return self._config_ctx

    @property
    def data_ctx(self) -> DataContext:
        """Get data context (database and repositories)."""
        if self._data_ctx is None:
            self._data_ctx = DataContext(
                _db=self._db,
                _host_repo=self._host_repo,
                _var_repo=self._var_repo,
                _conv_repo=self._conv_repo,
            )
        return self._data_ctx

    @property
    def exec_ctx(self) -> ExecutionContext:
        """Get execution context (SSH, elevation, MCP, router)."""
        if self._exec_ctx is None:
            self._exec_ctx = ExecutionContext(
                _config_ctx=self.config_ctx,
                _ssh_pool=self._ssh_pool,
                _router=self._router,
                _mcp_manager=self._mcp_manager,
            )
        return self._exec_ctx

    @property
    def ui_ctx(self) -> UIContext:
        """Get UI context (console, session passwords, cache)."""
        if self._ui_ctx is None:
            self._ui_ctx = UIContext(
                _config_ctx=self.config_ctx,
                _ui=self._ui,
                _session_passwords=self._session_passwords,
                _ask_user_cache=self._ask_user_cache,
                auto_confirm=self.auto_confirm,
                quiet=self.quiet,
                output_format=self.output_format,
            )
        return self._ui_ctx

    @property
    def session(self) -> SessionState:
        """Get session state (conversation context, password TTL)."""
        return self._session

    # Backward-compatible property: last_remote_target via session
    @property
    def last_remote_target(self) -> str | None:
        """Get last remote target (conversation context)."""
        return self._session.last_remote_target

    @last_remote_target.setter
    def last_remote_target(self, value: str | None) -> None:
        """Set last remote target (conversation context)."""
        self._session.last_remote_target = value

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

    async def get_elevation(self) -> ElevationManager:
        """Get elevation manager (lazy)."""
        if self._elevation is None:
            from merlya.security import ElevationManager

            self._elevation = ElevationManager(self)
        assert self._elevation is not None
        return self._elevation

    # Alias for backward compatibility
    async def get_permissions(self) -> ElevationManager:
        """Deprecated: use get_elevation() instead."""
        return await self.get_elevation()

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

    @property
    def session_passwords(self) -> SessionPasswordStore:
        """
        Get session password store (in-memory only).

        Passwords stored here are NOT persisted to keyring.
        They are cleared when the session ends.

        Use for:
        - Interactive sudo/su passwords
        - Temporary credentials
        - Passwords user doesn't want stored
        """
        if self._session_passwords is None:
            self._session_passwords = get_session_store()
            self._session_passwords.set_ui(self.ui)
        return self._session_passwords

    @property
    def ask_user_cache(self) -> AskUserCache:
        """Get ask user cache for input deduplication (lazy init)."""
        if self._ask_user_cache is None:
            from merlya.tools.core.user_input import AskUserCache

            self._ask_user_cache = AskUserCache()
        return self._ask_user_cache

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
            tier: Ignored (kept for backward compatibility, ONNX removed in v0.8.0).
        """
        _ = tier  # ONNX tiers no longer used

        from merlya.router import IntentRouter

        router = IntentRouter(
            use_local=False,  # ONNX removed - always use pattern/LLM
            config=self.config,  # Enable SmartExtractor (fast LLM)
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

        logger.debug("✅ Intent router initialized (pattern-based + LLM fallback)")

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

        # Clear session passwords (security: don't leave passwords in memory)
        if self._session_passwords:
            self._session_passwords.clear()
            self._session_passwords = None

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
