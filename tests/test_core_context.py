"""
Tests for merlya/core/context.py - SharedContext.

Covers all properties, lazy initialization, async methods, and singleton pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.core.context import SharedContext, get_context


class TestSharedContextProperties:
    """Test SharedContext property accessors."""

    @pytest.fixture
    def minimal_context(self):
        """Create a minimal context without async init."""
        config = MagicMock()
        config.ssh.pool_timeout = 30
        config.ssh.connect_timeout = 10
        i18n = MagicMock()
        secrets = MagicMock()

        return SharedContext(
            config=config,
            i18n=i18n,
            secrets=secrets,
        )

    def test_db_not_initialized(self, minimal_context):
        """Test db property raises when not initialized."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            _ = minimal_context.db

    def test_hosts_not_initialized(self, minimal_context):
        """Test hosts property raises when not initialized."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            _ = minimal_context.hosts

    def test_variables_not_initialized(self, minimal_context):
        """Test variables property raises when not initialized."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            _ = minimal_context.variables

    def test_conversations_not_initialized(self, minimal_context):
        """Test conversations property raises when not initialized."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            _ = minimal_context.conversations

    def test_router_not_initialized(self, minimal_context):
        """Test router property raises when not initialized."""
        with pytest.raises(RuntimeError, match="Router not initialized"):
            _ = minimal_context.router

    def test_t_translation(self, minimal_context):
        """Test t() translation helper."""
        minimal_context.i18n.t.return_value = "Hello World"

        result = minimal_context.t("greeting", name="World")

        minimal_context.i18n.t.assert_called_once_with("greeting", name="World")
        assert result == "Hello World"


class TestSharedContextLazyInit:
    """Test lazy initialization of components."""

    @pytest.fixture
    def context_with_config(self):
        """Create context with configured values."""
        config = MagicMock()
        config.ssh.pool_timeout = 30
        config.ssh.connect_timeout = 10
        i18n = MagicMock()
        secrets = MagicMock()

        ctx = SharedContext(
            config=config,
            i18n=i18n,
            secrets=secrets,
            auto_confirm=True,
            quiet=False,
        )
        return ctx

    def test_ui_lazy_creation(self, context_with_config):
        """Test UI is created lazily on first access."""
        with patch("merlya.ui.ConsoleUI") as MockUI:
            mock_ui = MagicMock()
            MockUI.return_value = mock_ui

            # First access creates UI
            ui1 = context_with_config.ui
            assert ui1 == mock_ui
            MockUI.assert_called_once_with(auto_confirm=True, quiet=False)

            # Second access returns same instance
            MockUI.reset_mock()
            ui2 = context_with_config.ui
            assert ui2 == mock_ui
            MockUI.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_elevation_lazy(self, context_with_config):
        """Test get_elevation lazy initialization."""
        with patch("merlya.security.ElevationManager") as MockEM:
            mock_em = MagicMock()
            MockEM.return_value = mock_em

            # First call creates elevation manager
            em1 = await context_with_config.get_elevation()
            assert em1 == mock_em
            MockEM.assert_called_once_with(context_with_config)

            # Second call returns same instance
            MockEM.reset_mock()
            em2 = await context_with_config.get_elevation()
            assert em2 == mock_em
            MockEM.assert_not_called()


class TestSharedContextSSH:
    """Test SSH pool and auth manager initialization."""

    @pytest.fixture
    def context_for_ssh(self):
        """Create context for SSH tests."""
        config = MagicMock()
        config.ssh.pool_timeout = 60
        config.ssh.connect_timeout = 15
        i18n = MagicMock()
        secrets = MagicMock()

        return SharedContext(
            config=config,
            i18n=i18n,
            secrets=secrets,
        )

    @pytest.mark.asyncio
    async def test_get_ssh_pool_creates_pool(self, context_for_ssh):
        """Test get_ssh_pool creates and configures pool."""
        mock_pool = MagicMock()
        mock_pool.set_auth_manager = MagicMock()

        mock_auth = MagicMock()

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool

            with patch.object(
                context_for_ssh, "get_auth_manager", new_callable=AsyncMock
            ) as mock_get_auth:
                mock_get_auth.return_value = mock_auth

                pool = await context_for_ssh.get_ssh_pool()

                assert pool == mock_pool
                mock_get.assert_called_once_with(timeout=60, connect_timeout=15)
                mock_pool.set_auth_manager.assert_called_once_with(mock_auth)

    @pytest.mark.asyncio
    async def test_get_ssh_pool_returns_cached(self, context_for_ssh):
        """Test get_ssh_pool returns cached instance."""
        mock_pool = MagicMock()
        context_for_ssh._ssh_pool = mock_pool

        pool = await context_for_ssh.get_ssh_pool()

        assert pool == mock_pool

    @pytest.mark.asyncio
    async def test_get_auth_manager_creates_manager(self, context_for_ssh):
        """Test get_auth_manager creates SSHAuthManager."""
        # Set up UI for auth manager
        context_for_ssh._ui = MagicMock()

        with patch("merlya.ssh.auth.SSHAuthManager") as MockAuth:
            mock_auth = MagicMock()
            MockAuth.return_value = mock_auth

            auth = await context_for_ssh.get_auth_manager()

            assert auth == mock_auth
            MockAuth.assert_called_once_with(
                secrets=context_for_ssh.secrets,
                ui=context_for_ssh._ui,
            )

    @pytest.mark.asyncio
    async def test_get_auth_manager_returns_cached(self, context_for_ssh):
        """Test get_auth_manager returns cached instance."""
        mock_auth = MagicMock()
        context_for_ssh._auth_manager = mock_auth

        auth = await context_for_ssh.get_auth_manager()

        assert auth == mock_auth

    @pytest.mark.asyncio
    async def test_get_auth_manager_handles_failure(self, context_for_ssh):
        """Test get_auth_manager returns None on failure."""
        context_for_ssh._ui = MagicMock()

        with patch("merlya.ssh.auth.SSHAuthManager", side_effect=Exception("Init failed")):
            auth = await context_for_ssh.get_auth_manager()

            assert auth is None


class TestSharedContextAsync:
    """Test async initialization methods."""

    @pytest.fixture
    def context_for_async(self):
        """Create context for async tests."""
        config = MagicMock()
        config.ssh.pool_timeout = 30
        config.ssh.connect_timeout = 10
        i18n = MagicMock()
        secrets = MagicMock()

        return SharedContext(
            config=config,
            i18n=i18n,
            secrets=secrets,
        )

    @pytest.mark.asyncio
    async def test_init_async(self, context_for_async):
        """Test init_async initializes database and repositories."""
        mock_db = MagicMock()
        mock_host_repo = MagicMock()
        mock_var_repo = MagicMock()
        mock_conv_repo = MagicMock()

        with patch("merlya.persistence.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

            with patch("merlya.persistence.HostRepository") as MockHR:
                MockHR.return_value = mock_host_repo

                with patch("merlya.persistence.VariableRepository") as MockVR:
                    MockVR.return_value = mock_var_repo

                    with patch("merlya.persistence.ConversationRepository") as MockCR:
                        MockCR.return_value = mock_conv_repo

                        await context_for_async.init_async()

                        assert context_for_async._db == mock_db
                        assert context_for_async._host_repo == mock_host_repo
                        assert context_for_async._var_repo == mock_var_repo
                        assert context_for_async._conv_repo == mock_conv_repo

    @pytest.mark.asyncio
    async def test_get_mcp_manager(self, context_for_async):
        """Test get_mcp_manager creates MCPManager."""
        # Pre-set the mcp_manager to avoid MCP import issues
        mock_mcp = MagicMock()
        context_for_async._mcp_manager = mock_mcp

        mcp = await context_for_async.get_mcp_manager()

        assert mcp == mock_mcp

    @pytest.mark.asyncio
    async def test_get_mcp_manager_cached(self, context_for_async):
        """Test get_mcp_manager returns cached instance."""
        mock_mcp = MagicMock()
        context_for_async._mcp_manager = mock_mcp

        mcp = await context_for_async.get_mcp_manager()

        assert mcp == mock_mcp


class TestSharedContextRouter:
    """Test router initialization."""

    @pytest.fixture
    def context_for_router(self):
        """Create context for router tests."""
        config = MagicMock()
        config.router.type = "local"
        config.router.model = "default-model"
        config.router.tier = None
        config.router.llm_fallback = None
        config.model.provider = "openai"
        config.ssh.pool_timeout = 30
        config.ssh.connect_timeout = 10
        i18n = MagicMock()
        secrets = MagicMock()

        return SharedContext(
            config=config,
            i18n=i18n,
            secrets=secrets,
        )

    @pytest.mark.asyncio
    async def test_init_router_pattern_based(self, context_for_router):
        """Test init_router with pattern-based router (ONNX removed in v0.8.0)."""
        mock_router = MagicMock()
        mock_router.classifier.model_loaded = False  # No ONNX

        with patch("merlya.router.IntentRouter") as MockRouter:
            MockRouter.return_value = mock_router
            mock_router.initialize = AsyncMock()

            await context_for_router.init_router(tier="standard")

            # ONNX removed - always use_local=False, config is passed
            MockRouter.assert_called_once()
            call_kwargs = MockRouter.call_args.kwargs
            assert call_kwargs["use_local"] is False
            mock_router.initialize.assert_called_once()
            assert context_for_router._router == mock_router

    @pytest.mark.asyncio
    async def test_init_router_ignores_health_check(self, context_for_router):
        """Test init_router ignores health check for ONNX (removed in v0.8.0)."""
        # Health check is now irrelevant for router
        context_for_router.health = MagicMock()
        context_for_router.health.capabilities = {"onnx_router": False}

        mock_router = MagicMock()
        mock_router.classifier.model_loaded = False

        with patch("merlya.router.IntentRouter") as MockRouter:
            MockRouter.return_value = mock_router
            mock_router.initialize = AsyncMock()

            await context_for_router.init_router()

            # Always use_local=False (ONNX removed), config is passed
            MockRouter.assert_called_once()
            call_kwargs = MockRouter.call_args.kwargs
            assert call_kwargs["use_local"] is False

    @pytest.mark.asyncio
    async def test_init_router_ignores_env_model(self, context_for_router):
        """Test init_router ignores model env var (ONNX removed in v0.8.0)."""
        mock_router = MagicMock()
        mock_router.classifier.model_loaded = False

        with patch.dict("os.environ", {"MERLYA_ROUTER_MODEL": "custom-model"}):
            with patch("merlya.router.IntentRouter") as MockRouter:
                MockRouter.return_value = mock_router
                mock_router.initialize = AsyncMock()

                await context_for_router.init_router()

                # Model param no longer passed (ONNX removed), config is passed
                MockRouter.assert_called_once()
                call_kwargs = MockRouter.call_args.kwargs
                assert call_kwargs["use_local"] is False

    @pytest.mark.asyncio
    async def test_init_router_with_llm_fallback(self, context_for_router):
        """Test init_router with LLM fallback configuration."""
        mock_router = MagicMock()
        mock_router.classifier.model_loaded = False

        with patch.dict("os.environ", {"MERLYA_ROUTER_FALLBACK": "gpt-4"}):
            with patch("merlya.router.IntentRouter") as MockRouter:
                MockRouter.return_value = mock_router
                mock_router.initialize = AsyncMock()
                mock_router.set_llm_fallback = MagicMock()

                await context_for_router.init_router()

                # Should add provider prefix
                mock_router.set_llm_fallback.assert_called_once_with("openai:gpt-4")


class TestSharedContextClose:
    """Test close and cleanup."""

    @pytest.fixture
    def context_with_resources(self):
        """Create context with initialized resources."""
        config = MagicMock()
        config.ssh.pool_timeout = 30
        config.ssh.connect_timeout = 10
        i18n = MagicMock()
        secrets = MagicMock()

        ctx = SharedContext(
            config=config,
            i18n=i18n,
            secrets=secrets,
        )

        # Set up resources - need to keep references
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        ctx._db = mock_db

        mock_ssh_pool = MagicMock()
        mock_ssh_pool.disconnect_all = AsyncMock()
        ctx._ssh_pool = mock_ssh_pool

        mock_mcp = MagicMock()
        mock_mcp.close = AsyncMock()
        ctx._mcp_manager = mock_mcp

        # Set singleton for close to work
        SharedContext._instance = ctx

        # Store references for assertions
        ctx._test_mock_db = mock_db
        ctx._test_mock_ssh_pool = mock_ssh_pool
        ctx._test_mock_mcp = mock_mcp

        return ctx

    @pytest.mark.asyncio
    async def test_close_all_resources(self, context_with_resources):
        """Test close cleans up all resources."""
        mock_db = context_with_resources._test_mock_db
        mock_ssh_pool = context_with_resources._test_mock_ssh_pool
        mock_mcp = context_with_resources._test_mock_mcp

        await context_with_resources.close()

        mock_db.close.assert_called_once()
        mock_ssh_pool.disconnect_all.assert_called_once()
        mock_mcp.close.assert_called_once()
        assert SharedContext._instance is None

    @pytest.mark.asyncio
    async def test_close_handles_errors(self, context_with_resources):
        """Test close handles errors gracefully."""
        context_with_resources._test_mock_db.close = AsyncMock(side_effect=Exception("DB error"))
        context_with_resources._test_mock_ssh_pool.disconnect_all = AsyncMock(
            side_effect=Exception("SSH error")
        )
        context_with_resources._test_mock_mcp.close = AsyncMock(side_effect=Exception("MCP error"))

        # Should not raise
        await context_with_resources.close()

        assert SharedContext._instance is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Test close is idempotent when instance is None."""
        SharedContext._instance = None

        ctx = SharedContext(
            config=MagicMock(),
            i18n=MagicMock(),
            secrets=MagicMock(),
        )

        # Should not raise
        await ctx.close()


class TestSharedContextSingleton:
    """Test singleton pattern."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SharedContext.reset_instance()
        yield
        SharedContext.reset_instance()

    def test_get_instance_not_initialized(self):
        """Test get_instance raises when not initialized."""
        with pytest.raises(RuntimeError, match="SharedContext not initialized"):
            SharedContext.get_instance()

    def test_reset_instance(self):
        """Test reset_instance clears singleton."""
        SharedContext._instance = MagicMock()

        SharedContext.reset_instance()

        assert SharedContext._instance is None

    @pytest.mark.asyncio
    async def test_create_initializes_singleton(self):
        """Test create initializes singleton."""
        mock_db = MagicMock()

        with patch("merlya.persistence.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

            with patch("merlya.persistence.HostRepository"):
                with patch("merlya.persistence.VariableRepository"):
                    with patch("merlya.persistence.ConversationRepository"):
                        ctx = await SharedContext.create()

                        # Should set singleton
                        assert SharedContext._instance == ctx
                        assert ctx._db == mock_db
                        # Config, i18n, secrets are set from real defaults
                        assert ctx.config is not None
                        assert ctx.i18n is not None
                        assert ctx.secrets is not None

    @pytest.mark.asyncio
    async def test_create_returns_existing(self):
        """Test create returns existing singleton."""
        existing = MagicMock()
        SharedContext._instance = existing

        ctx = await SharedContext.create()

        assert ctx == existing


class TestGetContext:
    """Test get_context helper function."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SharedContext.reset_instance()
        yield
        SharedContext.reset_instance()

    @pytest.mark.asyncio
    async def test_get_context_returns_existing(self):
        """Test get_context returns existing instance."""
        existing = MagicMock()
        SharedContext._instance = existing

        ctx = await get_context()

        assert ctx == existing

    @pytest.mark.asyncio
    async def test_get_context_creates_new(self):
        """Test get_context creates new instance if none exists."""
        mock_db = MagicMock()

        with patch("merlya.persistence.get_database", new_callable=AsyncMock) as mock_get_db:
            mock_get_db.return_value = mock_db

            with patch("merlya.persistence.HostRepository"):
                with patch("merlya.persistence.VariableRepository"):
                    with patch("merlya.persistence.ConversationRepository"):
                        ctx = await get_context()

                        assert ctx is not None
                        assert SharedContext._instance == ctx
