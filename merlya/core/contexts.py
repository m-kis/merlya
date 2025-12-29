"""
Merlya Core - Focused Context Classes.

Splits the monolithic SharedContext into focused, single-responsibility contexts:
- ConfigContext: Application configuration and settings
- DataContext: Database and repository access
- ExecutionContext: Runtime services (SSH, elevation, MCP)
- UIContext: User interface and interaction
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.config import Config
    from merlya.health import StartupHealth
    from merlya.i18n import I18n
    from merlya.mcp import MCPManager
    from merlya.persistence import (
        ConversationRepository,
        Database,
        HostRepository,
        VariableRepository,
    )
    from merlya.router import IntentRouter
    from merlya.secrets import SecretStore
    from merlya.secrets.session import SessionPasswordStore
    from merlya.security import ElevationManager
    from merlya.ssh import SSHPool
    from merlya.tools.core.user_input import AskUserCache
    from merlya.ui import ConsoleUI


@dataclass
class ConfigContext:
    """
    Configuration-focused context.

    Provides access to application settings, i18n, and secrets.
    This is immutable after initialization.
    """

    config: Config
    i18n: I18n
    secrets: SecretStore
    health: StartupHealth | None = None

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate a key using the i18n instance."""
        return self.i18n.t(key, **kwargs)

    @property
    def language(self) -> str:
        """Get current language."""
        return self.config.general.language

    @property
    def provider(self) -> str:
        """Get LLM provider name."""
        return self.config.model.provider


@dataclass
class DataContext:
    """
    Data-focused context.

    Provides access to database and repositories.
    Thread-safe repository access.
    """

    _db: Database | None = field(default=None, repr=False)
    _host_repo: HostRepository | None = field(default=None, repr=False)
    _var_repo: VariableRepository | None = field(default=None, repr=False)
    _conv_repo: ConversationRepository | None = field(default=None, repr=False)

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

    async def init_async(self) -> None:
        """Initialize async components (database, repositories)."""
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

        logger.debug("✅ DataContext initialized")

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            try:
                await self._db.close()
            except Exception as e:
                logger.debug(f"DB close error: {e}")
            self._db = None


@dataclass
class ExecutionContext:
    """
    Execution-focused context.

    Provides access to runtime services: SSH pool, elevation, MCP, router.
    These are lazily initialized on first access.
    """

    _config_ctx: ConfigContext = field(repr=False)

    # Lazy-initialized services
    _ssh_pool: SSHPool | None = field(default=None, repr=False)
    _elevation: ElevationManager | None = field(default=None, repr=False)
    _auth_manager: object | None = field(default=None, repr=False)
    _router: IntentRouter | None = field(default=None, repr=False)
    _mcp_manager: MCPManager | None = field(default=None, repr=False)

    async def get_ssh_pool(self) -> SSHPool:
        """Get SSH connection pool (async, lazy)."""
        if self._ssh_pool is None:
            from merlya.ssh import SSHPool

            self._ssh_pool = await SSHPool.get_instance(
                timeout=self._config_ctx.config.ssh.pool_timeout,
                connect_timeout=self._config_ctx.config.ssh.connect_timeout,
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
                from merlya.ui import ConsoleUI

                # Create minimal UI for auth prompts
                ui = ConsoleUI(auto_confirm=False, quiet=False)

                self._auth_manager = SSHAuthManager(
                    secrets=self._config_ctx.secrets,
                    ui=ui,
                )
                logger.debug("SSH auth manager initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize SSH auth manager: {e}")
                return None
        return self._auth_manager

    async def get_elevation(self) -> ElevationManager:
        """Get elevation manager (lazy)."""
        if self._elevation is None:
            # Elevation needs full SharedContext, defer to parent
            raise RuntimeError(
                "ElevationManager requires full SharedContext. "
                "Use SharedContext.get_elevation() instead."
            )
        return self._elevation

    def set_elevation(self, elevation: ElevationManager) -> None:
        """Set elevation manager (called from SharedContext)."""
        self._elevation = elevation

    @property
    def router(self) -> IntentRouter:
        """Get intent router."""
        if self._router is None:
            raise RuntimeError("Router not initialized. Call init_router() first.")
        return self._router

    def set_router(self, router: IntentRouter) -> None:
        """Set intent router."""
        self._router = router

    async def get_mcp_manager(self) -> MCPManager:
        """Get MCP manager (lazy, async-safe)."""
        if self._mcp_manager is None:
            from merlya.mcp import MCPManager

            self._mcp_manager = await MCPManager.create(
                self._config_ctx.config, self._config_ctx.secrets
            )
        return self._mcp_manager

    async def close(self) -> None:
        """Close all services."""
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


@dataclass
class UIContext:
    """
    UI-focused context.

    Provides access to console UI and user interaction.
    """

    _config_ctx: ConfigContext = field(repr=False)

    # UI components
    _ui: ConsoleUI | None = field(default=None, repr=False)
    _session_passwords: SessionPasswordStore | None = field(default=None, repr=False)
    _ask_user_cache: AskUserCache | None = field(default=None, repr=False)

    # Non-interactive mode flags
    auto_confirm: bool = field(default=False)
    quiet: bool = field(default=False)
    output_format: str = field(default="text")

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
        """
        if self._session_passwords is None:
            from merlya.secrets.session import get_session_store

            self._session_passwords = get_session_store()
            self._session_passwords.set_ui(self.ui)
        return self._session_passwords

    @property
    def ask_user_cache(self) -> AskUserCache:
        """Get ask user cache for input deduplication."""
        if self._ask_user_cache is None:
            from merlya.tools.core.user_input import AskUserCache

            self._ask_user_cache = AskUserCache()
        return self._ask_user_cache

    def clear_session(self) -> None:
        """Clear session data (passwords, cache)."""
        if self._session_passwords:
            self._session_passwords.clear()
            self._session_passwords = None


@dataclass
class SessionState:
    """
    Session state for conversation context.

    Tracks transient state within a conversation session.
    """

    # Last remote target for follow-up questions
    # e.g., "check disk on pine64" followed by "what's using the most space?"
    last_remote_target: str | None = None

    # Session start time
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Cached password TTLs (host -> expiry time)
    _password_expiry: dict[str, datetime] = field(default_factory=dict)

    # Default password TTL
    password_ttl_seconds: int = 3600  # 1 hour

    def set_password_expiry(self, host: str, ttl_seconds: int | None = None) -> None:
        """Set password expiry for a host."""
        ttl = ttl_seconds or self.password_ttl_seconds
        self._password_expiry[host] = datetime.now(UTC) + timedelta(seconds=ttl)

    def is_password_expired(self, host: str) -> bool:
        """Check if password for host has expired."""
        expiry = self._password_expiry.get(host)
        if expiry is None:
            return True
        return datetime.now(UTC) > expiry

    def clear_expired_passwords(self) -> list[str]:
        """Clear expired password entries and return their hostnames."""
        now = datetime.now(UTC)
        expired = [h for h, exp in self._password_expiry.items() if now > exp]
        for h in expired:
            del self._password_expiry[h]
        return expired

    def reset(self) -> None:
        """Reset session state."""
        self.last_remote_target = None
        self._password_expiry.clear()
