"""
Tests for /ssh command and subcommands.

Tests SSH connection management commands including connect,
exec, disconnect, config, and test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers import init_commands
from merlya.commands.registry import CommandRegistry, get_registry
from merlya.i18n.loader import I18n


@pytest.fixture
def registry() -> CommandRegistry:
    """Get initialized command registry."""
    init_commands()
    return get_registry()


@pytest.fixture
def mock_ssh_pool() -> MagicMock:
    """Create a mock SSH pool."""
    pool = MagicMock()
    pool.get_connection = AsyncMock()
    pool.execute = AsyncMock()
    pool.disconnect = AsyncMock()
    pool.disconnect_all = AsyncMock()
    pool.has_passphrase_callback = MagicMock(return_value=True)
    pool.has_mfa_callback = MagicMock(return_value=True)
    pool.set_passphrase_callback = MagicMock()
    pool.set_mfa_callback = MagicMock()
    return pool


@pytest.fixture
def mock_context(mock_ssh_pool: MagicMock) -> MagicMock:
    """Create a mock SharedContext with all required attributes."""
    ctx = MagicMock(
        spec=[
            "ui",
            "hosts",
            "variables",
            "conversations",
            "secrets",
            "i18n",
            "config",
            "t",
            "get_ssh_pool",
        ]
    )

    # Mock UI
    ctx.ui = MagicMock()
    ctx.ui.prompt = AsyncMock(return_value="test_value")
    ctx.ui.prompt_confirm = AsyncMock(return_value=True)
    ctx.ui.prompt_secret = AsyncMock(return_value="secret_value")
    ctx.ui.info = MagicMock()
    ctx.ui.muted = MagicMock()
    ctx.ui.success = MagicMock()
    ctx.ui.warning = MagicMock()
    ctx.ui.error = MagicMock()
    ctx.ui.spinner = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))

    # Mock i18n
    ctx.i18n = I18n("en")
    ctx.t = ctx.i18n.t

    # Mock config
    ctx.config = MagicMock()
    ctx.config.general = MagicMock()
    ctx.config.general.data_dir = Path(tempfile.mkdtemp())
    ctx.config.ssh = MagicMock()
    ctx.config.ssh.default_timeout = 30
    ctx.config.ssh.connection_timeout = 10
    ctx.config.save = MagicMock()

    # Mock secrets
    ctx.secrets = MagicMock()
    ctx.secrets.list_keys = MagicMock(return_value=[])
    ctx.secrets.set = MagicMock()
    ctx.secrets.get = MagicMock(return_value=None)
    ctx.secrets.delete = MagicMock()
    ctx.secrets.has = MagicMock(return_value=False)

    # Mock SSH pool
    ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

    return ctx


@pytest.fixture
def mock_hosts_repo(mock_context: MagicMock) -> MagicMock:
    """Configure hosts repository mock."""
    from merlya.persistence.models import Host

    test_host = Host(
        name="test-host",
        hostname="192.168.1.1",
        port=22,
        username="admin",
        tags=["web", "prod"],
        health_status="healthy",
    )

    mock_context.hosts = MagicMock()
    mock_context.hosts.get_all = AsyncMock(return_value=[test_host])
    mock_context.hosts.get_by_name = AsyncMock(return_value=test_host)
    mock_context.hosts.get_by_tag = AsyncMock(return_value=[test_host])
    mock_context.hosts.create = AsyncMock(return_value=test_host)
    mock_context.hosts.update = AsyncMock(return_value=test_host)
    mock_context.hosts.delete = AsyncMock(return_value=True)
    mock_context.hosts.count = AsyncMock(return_value=1)

    return mock_context.hosts


class TestSSHConnectCommand:
    """Tests for /ssh connect command."""

    async def test_ssh_connect_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /ssh connect without args shows usage."""
        result = await registry.execute(mock_context, "/ssh connect")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_ssh_connect_host_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /ssh connect with unknown host."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/ssh connect unknown")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_ssh_connect_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
        mock_ssh_pool: MagicMock,
    ):
        """Test /ssh connect with valid host."""
        result = await registry.execute(mock_context, "/ssh connect test-host")
        assert result is not None
        assert result.success is True
        mock_ssh_pool.get_connection.assert_called_once()


class TestSSHExecCommand:
    """Tests for /ssh exec command."""

    async def test_ssh_exec_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /ssh exec without args shows usage."""
        result = await registry.execute(mock_context, "/ssh exec")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_ssh_exec_no_command(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /ssh exec with host but no command."""
        result = await registry.execute(mock_context, "/ssh exec test-host")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_ssh_exec_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
        mock_ssh_pool: MagicMock,
    ):
        """Test /ssh exec with valid host and command."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_ssh_pool.execute = AsyncMock(return_value=mock_result)

        result = await registry.execute(mock_context, "/ssh exec test-host uptime")
        assert result is not None
        assert result.success is True


class TestSSHDisconnectCommand:
    """Tests for /ssh disconnect command."""

    async def test_ssh_disconnect_all(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
        mock_ssh_pool: MagicMock,
    ):
        """Test /ssh disconnect without args disconnects all."""
        result = await registry.execute(mock_context, "/ssh disconnect")
        assert result is not None
        assert result.success is True
        mock_ssh_pool.disconnect_all.assert_called_once()

    async def test_ssh_disconnect_specific_host(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
        mock_ssh_pool: MagicMock,
    ):
        """Test /ssh disconnect with valid host."""
        result = await registry.execute(mock_context, "/ssh disconnect test-host")
        assert result is not None
        assert result.success is True
        mock_ssh_pool.disconnect.assert_called_once_with("test-host")


class TestSSHConfigCommand:
    """Tests for /ssh config command."""

    async def test_ssh_config_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /ssh config without args shows usage."""
        result = await registry.execute(mock_context, "/ssh config")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_ssh_config_host_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /ssh config with unknown host."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/ssh config unknown")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()


class TestSSHTestCommand:
    """Tests for /ssh test command."""

    async def test_ssh_test_no_args(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
    ):
        """Test /ssh test without args shows usage."""
        result = await registry.execute(mock_context, "/ssh test")
        assert result is not None
        assert result.success is False
        assert "Usage" in result.message

    async def test_ssh_test_host_not_found(
        self, registry: CommandRegistry, mock_context: MagicMock, mock_hosts_repo: MagicMock
    ):
        """Test /ssh test with unknown host."""
        mock_hosts_repo.get_by_name = AsyncMock(return_value=None)
        result = await registry.execute(mock_context, "/ssh test unknown")
        assert result is not None
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_ssh_test_success(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
        mock_ssh_pool: MagicMock,
    ):
        """Test /ssh test with successful connection."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_ssh_pool.execute = AsyncMock(return_value=mock_result)

        result = await registry.execute(mock_context, "/ssh test test-host")
        assert result is not None
        assert result.success is True

    async def test_ssh_test_failure(
        self,
        registry: CommandRegistry,
        mock_context: MagicMock,
        mock_hosts_repo: MagicMock,
        mock_ssh_pool: MagicMock,
    ):
        """Test /ssh test with failed connection."""
        mock_ssh_pool.execute = AsyncMock(side_effect=Exception("Connection refused"))

        result = await registry.execute(mock_context, "/ssh test test-host")
        assert result is not None
        assert result.success is False
