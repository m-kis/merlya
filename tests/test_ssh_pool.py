"""Tests for SSH connection pool."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from merlya.ssh.pool import SSHConnectionOptions, SSHPool


class TestSSHPoolSingleton:
    """Tests for SSHPool singleton pattern."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_get_instance_creates_singleton(self) -> None:
        """Test that get_instance creates singleton."""
        pool1 = await SSHPool.get_instance()
        pool2 = await SSHPool.get_instance()

        assert pool1 is pool2

    @pytest.mark.asyncio
    async def test_get_instance_thread_safe(self) -> None:
        """Test that concurrent calls return same instance."""
        results = await asyncio.gather(
            SSHPool.get_instance(),
            SSHPool.get_instance(),
            SSHPool.get_instance(),
        )

        assert all(r is results[0] for r in results)

    def test_reset_instance(self) -> None:
        """Test reset clears singleton."""
        SSHPool._instance = MagicMock()
        SSHPool.reset_instance()

        assert SSHPool._instance is None


class TestSSHPoolKnownHosts:
    """Tests for known_hosts security."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_known_hosts_default_path(self) -> None:
        """Test that known_hosts uses default path when available."""
        pool = await SSHPool.get_instance()

        with patch.object(Path, "exists", return_value=True):
            path = pool._get_known_hosts_path()

        assert path is not None
        assert "known_hosts" in path

    @pytest.mark.asyncio
    async def test_known_hosts_none_when_missing(self) -> None:
        """Test that known_hosts returns None when file missing."""
        pool = await SSHPool.get_instance()

        with patch.object(Path, "exists", return_value=False):
            path = pool._get_known_hosts_path()

        assert path is None


class TestSSHPoolLimits:
    """Tests for connection limits."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_default_max_connections(self) -> None:
        """Test default max connections."""
        pool = await SSHPool.get_instance()
        assert pool.max_connections == SSHPool.DEFAULT_MAX_CONNECTIONS

    @pytest.mark.asyncio
    async def test_custom_max_connections(self) -> None:
        """Test custom max connections."""
        pool = await SSHPool.get_instance(max_connections=10)
        assert pool.max_connections == 10

    @pytest.mark.asyncio
    async def test_evict_lru_when_full(self) -> None:
        """Test LRU eviction when pool is full."""
        from datetime import datetime, timedelta

        from merlya.ssh.pool import SSHConnection

        pool = await SSHPool.get_instance(max_connections=2)

        # Create mock SSHConnection objects with different last_used times
        now = datetime.now(UTC)
        old_conn = SSHConnection(
            host="host1",
            connection=MagicMock(),
            last_used=now - timedelta(hours=1),  # Older
        )
        old_conn.close = AsyncMock()

        new_conn = SSHConnection(
            host="host2",
            connection=MagicMock(),
            last_used=now,  # Newer
        )
        new_conn.close = AsyncMock()

        pool._connections = {
            "host1": old_conn,
            "host2": new_conn,
        }

        await pool._evict_lru_connection()

        assert "host1" not in pool._connections
        assert "host2" in pool._connections


class TestSSHPoolPortValidation:
    """Tests for port validation."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_port_validation_invalid_zero(self) -> None:
        """Test that port 0 is rejected."""
        pool = await SSHPool.get_instance()

        with pytest.raises(ValueError, match="Invalid port number"):
            await pool.get_connection("host", options=SSHConnectionOptions(port=0))

    @pytest.mark.asyncio
    async def test_port_validation_invalid_negative(self) -> None:
        """Test that negative port is rejected."""
        pool = await SSHPool.get_instance()

        with pytest.raises(ValueError, match="Invalid port number"):
            await pool.get_connection("host", options=SSHConnectionOptions(port=-1))

    @pytest.mark.asyncio
    async def test_port_validation_invalid_too_high(self) -> None:
        """Test that port > 65535 is rejected."""
        pool = await SSHPool.get_instance()

        with pytest.raises(ValueError, match="Invalid port number"):
            await pool.get_connection("host", options=SSHConnectionOptions(port=65536))


class TestSSHPoolExecute:
    """Tests for command execution."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_execute_validates_command(self) -> None:
        """Test that execute validates command."""
        pool = await SSHPool.get_instance()

        # Empty command should fail
        with pytest.raises(ValueError, match="cannot be empty"):
            await pool.execute("host", "")

    @pytest.mark.asyncio
    async def test_execute_validates_hostname(self) -> None:
        """Test that execute validates hostname."""
        pool = await SSHPool.get_instance()

        with pytest.raises(ValueError, match="cannot be empty"):
            await pool.execute("", "ls")


class TestSSHPoolPassphrase:
    """Tests for passphrase callback invocation on encrypted key."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_passphrase_callback_used_on_keyimporterror(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Ensure KeyImportError triggers passphrase callback."""
        pool = await SSHPool.get_instance()
        pool._passphrase_callback = lambda _p: "secret-pass"

        key_file = tmp_path / "id_rsa"
        key_file.write_text("dummy")

        call_order: list[str] = []

        def fake_read_private_key(_path: str, passphrase: str | None = None):
            if passphrase is None:
                call_order.append("first")
                raise asyncssh.KeyImportError(
                    "Passphrase must be specified to import encrypted private keys"
                )
            call_order.append("second")
            return MagicMock()

        monkeypatch.setattr("asyncssh.read_private_key", fake_read_private_key)
        monkeypatch.setattr(Path, "exists", lambda _self: True)

        key = await pool._load_private_key(key_file)

        assert call_order == ["first", "second"]
        assert key is not None


# ==============================================================================
# Additional Tests for Higher Coverage
# ==============================================================================


class TestSSHPoolCallbacks:
    """Tests for callback methods."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_set_mfa_callback(self) -> None:
        """Test setting MFA callback."""
        pool = await SSHPool.get_instance()

        def callback(prompt):
            return "123456"

        pool.set_mfa_callback(callback)

        assert pool.has_mfa_callback() is True
        assert pool._mfa_callback is callback

    @pytest.mark.asyncio
    async def test_has_mfa_callback_false(self) -> None:
        """Test MFA callback not set."""
        pool = await SSHPool.get_instance()
        assert pool.has_mfa_callback() is False

    @pytest.mark.asyncio
    async def test_set_passphrase_callback(self) -> None:
        """Test setting passphrase callback."""
        pool = await SSHPool.get_instance()

        def callback(path):
            return "secret"

        pool.set_passphrase_callback(callback)

        assert pool.has_passphrase_callback() is True
        assert pool._passphrase_callback is callback

    @pytest.mark.asyncio
    async def test_has_passphrase_callback_false(self) -> None:
        """Test passphrase callback not set."""
        pool = await SSHPool.get_instance()
        assert pool.has_passphrase_callback() is False

    @pytest.mark.asyncio
    async def test_set_auth_manager(self) -> None:
        """Test setting auth manager."""
        pool = await SSHPool.get_instance()
        mock_manager = MagicMock()

        pool.set_auth_manager(mock_manager)

        assert pool._auth_manager is mock_manager


class TestSSHPoolConnectionLock:
    """Tests for connection lock handling."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_get_connection_lock_creates_new(self) -> None:
        """Test that connection lock is created for new key."""
        pool = await SSHPool.get_instance()

        lock = await pool._get_connection_lock("user@host:22")

        assert lock is not None
        assert "user@host:22" in pool._connection_locks

    @pytest.mark.asyncio
    async def test_get_connection_lock_reuses_existing(self) -> None:
        """Test that existing lock is reused."""
        pool = await SSHPool.get_instance()

        lock1 = await pool._get_connection_lock("user@host:22")
        lock2 = await pool._get_connection_lock("user@host:22")

        assert lock1 is lock2


class TestSSHPoolEviction:
    """Tests for connection eviction."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_evict_lru_empty_pool(self) -> None:
        """Test eviction on empty pool does nothing."""
        pool = await SSHPool.get_instance()
        pool._connections = {}

        # Should not raise
        await pool._evict_lru_connection()

        assert pool._connections == {}


class TestSSHPoolHasConnection:
    """Tests for has_connection method."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_has_connection_true(self) -> None:
        """Test has_connection returns True for active connection."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        conn = SSHConnection(host="192.168.1.1", connection=mock_conn)
        conn.is_alive = MagicMock(return_value=True)
        pool._connections = {"user@192.168.1.1:22": conn}

        assert pool.has_connection("192.168.1.1") is True

    @pytest.mark.asyncio
    async def test_has_connection_false_not_found(self) -> None:
        """Test has_connection returns False when not found."""
        pool = await SSHPool.get_instance()
        pool._connections = {}

        assert pool.has_connection("unknown-host") is False

    @pytest.mark.asyncio
    async def test_has_connection_false_expired(self) -> None:
        """Test has_connection returns False for expired connection."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        conn = SSHConnection(host="192.168.1.1", connection=mock_conn)
        conn.is_alive = MagicMock(return_value=False)
        pool._connections = {"user@192.168.1.1:22": conn}

        assert pool.has_connection("192.168.1.1") is False

    @pytest.mark.asyncio
    async def test_has_connection_with_port(self) -> None:
        """Test has_connection with port filter."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        conn = SSHConnection(host="192.168.1.1", connection=mock_conn)
        conn.is_alive = MagicMock(return_value=True)
        pool._connections = {"user@192.168.1.1:2222": conn}

        assert pool.has_connection("192.168.1.1", port=2222) is True
        assert pool.has_connection("192.168.1.1", port=22) is False

    @pytest.mark.asyncio
    async def test_has_connection_with_username(self) -> None:
        """Test has_connection with username filter."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        conn = SSHConnection(host="192.168.1.1", connection=mock_conn)
        conn.is_alive = MagicMock(return_value=True)
        pool._connections = {"admin@192.168.1.1:22": conn}

        assert pool.has_connection("192.168.1.1", username="admin") is True
        assert pool.has_connection("192.168.1.1", username="root") is False


class TestSSHPoolDisconnect:
    """Tests for disconnect methods."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_disconnect_single_host(self) -> None:
        """Test disconnecting a single host."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        conn = SSHConnection(host="host1", connection=mock_conn)
        conn.close = AsyncMock()
        pool._connections = {"user@host1:22": conn}

        await pool.disconnect("host1")

        assert "user@host1:22" not in pool._connections
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_host(self) -> None:
        """Test disconnecting non-existent host does nothing."""
        pool = await SSHPool.get_instance()
        pool._connections = {}

        # Should not raise
        await pool.disconnect("nonexistent")

    @pytest.mark.asyncio
    async def test_disconnect_all(self) -> None:
        """Test disconnecting all connections."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn1 = MagicMock()
        conn1 = SSHConnection(host="host1", connection=mock_conn1)
        conn1.close = AsyncMock()

        mock_conn2 = MagicMock()
        conn2 = SSHConnection(host="host2", connection=mock_conn2)
        conn2.close = AsyncMock()

        pool._connections = {
            "user@host1:22": conn1,
            "user@host2:22": conn2,
        }
        pool._connection_locks = {
            "user@host1:22": asyncio.Lock(),
            "user@host2:22": asyncio.Lock(),
        }

        await pool.disconnect_all()

        assert pool._connections == {}
        assert pool._connection_locks == {}
        conn1.close.assert_called_once()
        conn2.close.assert_called_once()


class TestSSHPoolMFAClient:
    """Tests for MFA client creation."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_create_mfa_client_no_callback(self) -> None:
        """Test MFA client not created without callback."""
        pool = await SSHPool.get_instance()
        pool._mfa_callback = None

        client = pool._create_mfa_client()

        assert client is None

    @pytest.mark.asyncio
    async def test_create_mfa_client_with_callback(self) -> None:
        """Test MFA client created with callback."""
        pool = await SSHPool.get_instance()
        pool._mfa_callback = lambda prompt: "123456"

        client_class = pool._create_mfa_client()

        assert client_class is not None
        # Verify it's a class
        assert isinstance(client_class, type)


class TestSSHPoolJumpHost:
    """Tests for jump host handling."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_setup_jump_tunnel_no_jump_host(self) -> None:
        """Test no tunnel created without jump host."""
        pool = await SSHPool.get_instance()
        opts = SSHConnectionOptions(jump_host=None)

        tunnel = await pool._setup_jump_tunnel(opts)

        assert tunnel is None

    @pytest.mark.asyncio
    async def test_load_jump_key_success(self, tmp_path: Path) -> None:
        """Test loading jump key without passphrase."""
        pool = await SSHPool.get_instance()
        key_file = tmp_path / "jump_key"
        key_file.write_text("dummy key")

        mock_key = MagicMock()
        with patch("asyncssh.read_private_key", return_value=mock_key):
            key = await pool._load_jump_key(key_file)

        assert key is mock_key

    @pytest.mark.asyncio
    async def test_load_jump_key_encrypted_with_callback(self, tmp_path: Path) -> None:
        """Test loading encrypted jump key with passphrase callback."""
        pool = await SSHPool.get_instance()
        pool._passphrase_callback = lambda path: "secret"
        key_file = tmp_path / "jump_key"
        key_file.write_text("encrypted key")

        mock_key = MagicMock()

        def mock_read_key(path, passphrase=None):
            if passphrase is None:
                raise asyncssh.KeyEncryptionError("Encrypted")
            return mock_key

        with patch("asyncssh.read_private_key", side_effect=mock_read_key):
            key = await pool._load_jump_key(key_file)

        assert key is mock_key

    @pytest.mark.asyncio
    async def test_load_jump_key_encrypted_no_callback(self, tmp_path: Path) -> None:
        """Test loading encrypted jump key without callback returns None."""
        pool = await SSHPool.get_instance()
        pool._passphrase_callback = None
        key_file = tmp_path / "jump_key"
        key_file.write_text("encrypted key")

        with patch(
            "asyncssh.read_private_key", side_effect=asyncssh.KeyEncryptionError("Encrypted")
        ):
            key = await pool._load_jump_key(key_file)

        assert key is None


class TestSSHPoolPrivateKey:
    """Tests for private key loading."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_load_private_key_unencrypted(self, tmp_path: Path) -> None:
        """Test loading unencrypted private key."""
        pool = await SSHPool.get_instance()
        key_file = tmp_path / "id_rsa"
        key_file.write_text("unencrypted key")

        mock_key = MagicMock()
        with patch("asyncssh.read_private_key", return_value=mock_key):
            key = await pool._load_private_key(key_file)

        assert key is mock_key

    @pytest.mark.asyncio
    async def test_load_private_key_encrypted_no_callback_raises(self, tmp_path: Path) -> None:
        """Test loading encrypted key without callback raises."""
        pool = await SSHPool.get_instance()
        pool._passphrase_callback = None
        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted key")

        with patch(
            "asyncssh.read_private_key", side_effect=asyncssh.KeyEncryptionError("Encrypted")
        ):
            with pytest.raises(asyncssh.KeyEncryptionError):
                await pool._load_private_key(key_file)

    @pytest.mark.asyncio
    async def test_load_private_key_callback_returns_none_raises(self, tmp_path: Path) -> None:
        """Test encrypted key with callback returning None raises."""
        pool = await SSHPool.get_instance()
        pool._passphrase_callback = lambda path: None  # Returns None
        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted key")

        with patch(
            "asyncssh.read_private_key", side_effect=asyncssh.KeyEncryptionError("Encrypted")
        ):
            with pytest.raises(asyncssh.KeyEncryptionError, match="Passphrase required"):
                await pool._load_private_key(key_file)


class TestSSHPoolValidateKey:
    """Tests for key validation."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_validate_private_key_delegates(self) -> None:
        """Test validate_private_key delegates to validation module."""
        with patch(
            "merlya.ssh.pool._validate_private_key", new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = (True, "Key is valid")

            result = await SSHPool.validate_private_key("/path/to/key")

            assert result == (True, "Key is valid")
            mock_validate.assert_called_once_with("/path/to/key", None)

    @pytest.mark.asyncio
    async def test_validate_private_key_with_passphrase(self) -> None:
        """Test validate_private_key with passphrase."""
        with patch(
            "merlya.ssh.pool._validate_private_key", new_callable=AsyncMock
        ) as mock_validate:
            mock_validate.return_value = (True, "Key is valid")

            await SSHPool.validate_private_key("/path/to/key", "secret")

            mock_validate.assert_called_once_with("/path/to/key", "secret")


class TestSSHPoolInitialization:
    """Tests for pool initialization."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_init_defaults(self) -> None:
        """Test pool initialization with defaults."""
        pool = await SSHPool.get_instance()

        assert pool.timeout == SSHPool.DEFAULT_TIMEOUT
        assert pool.connect_timeout == SSHPool.DEFAULT_CONNECT_TIMEOUT
        assert pool.max_connections == SSHPool.DEFAULT_MAX_CONNECTIONS
        assert pool.auto_add_host_keys is True

    @pytest.mark.asyncio
    async def test_init_custom_values(self) -> None:
        """Test pool initialization with custom values."""
        pool = await SSHPool.get_instance(
            timeout=300,
            connect_timeout=15,
            max_connections=25,
        )

        assert pool.timeout == 300
        assert pool.connect_timeout == 15
        assert pool.max_connections == 25


# ==============================================================================
# Tests for _build_ssh_options
# ==============================================================================


class TestSSHPoolBuildSSHOptions:
    """Tests for _build_ssh_options method."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_build_options_with_auth_manager(self) -> None:
        """Test building SSH options with auth manager."""
        from merlya.ssh.auth import SSHAuthManager

        pool = await SSHPool.get_instance()

        # Create mock auth options
        mock_auth_opts = MagicMock()
        mock_auth_opts.preferred_auth = ["publickey"]
        mock_auth_opts.client_keys = ["key1"]
        mock_auth_opts.password = "secret"
        mock_auth_opts.agent_path = "/tmp/agent"

        # Create mock auth manager that passes isinstance check
        mock_auth_manager = MagicMock(spec=SSHAuthManager)
        mock_auth_manager.prepare_auth = AsyncMock(return_value=mock_auth_opts)

        pool._auth_manager = mock_auth_manager

        opts = SSHConnectionOptions()
        options = await pool._build_ssh_options("host1", "user", None, opts)

        assert options["preferred_auth"] == ["publickey"]
        assert options["client_keys"] == ["key1"]
        assert options["password"] == "secret"
        assert options["agent_path"] == "/tmp/agent"

    @pytest.mark.asyncio
    async def test_build_options_no_auth_manager_with_agent(self) -> None:
        """Test building SSH options without auth manager but with agent."""
        pool = await SSHPool.get_instance()
        pool._auth_manager = None

        opts = SSHConnectionOptions()
        with patch.dict("os.environ", {"SSH_AUTH_SOCK": "/tmp/ssh-agent"}):
            options = await pool._build_ssh_options("host1", "user", "/path/to/key", opts)

        assert options["preferred_auth"] == "publickey,keyboard-interactive"
        assert "client_keys" not in options  # Agent handles keys

    @pytest.mark.asyncio
    async def test_build_options_no_auth_manager_no_agent(self, tmp_path: Path) -> None:
        """Test building SSH options without auth manager and no agent."""
        pool = await SSHPool.get_instance()
        pool._auth_manager = None

        # Create a mock key file
        key_file = tmp_path / "id_rsa"
        key_file.write_text("mock key content")

        mock_key = MagicMock()
        opts = SSHConnectionOptions()

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(
                pool, "_load_private_key", new_callable=AsyncMock, return_value=mock_key
            ):
                options = await pool._build_ssh_options("host1", "user", str(key_file), opts)

        assert options["client_keys"] == [mock_key]

    @pytest.mark.asyncio
    async def test_build_options_key_not_found(self) -> None:
        """Test building SSH options with non-existent key file."""
        pool = await SSHPool.get_instance()
        pool._auth_manager = None

        opts = SSHConnectionOptions()
        with patch.dict("os.environ", {}, clear=True):
            options = await pool._build_ssh_options("host1", "user", "/nonexistent/key", opts)

        assert "client_keys" not in options

    @pytest.mark.asyncio
    async def test_build_options_key_load_fails(self, tmp_path: Path) -> None:
        """Test building SSH options when key loading fails."""
        pool = await SSHPool.get_instance()
        pool._auth_manager = None

        key_file = tmp_path / "id_rsa"
        key_file.write_text("bad key")

        opts = SSHConnectionOptions()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(
                pool,
                "_load_private_key",
                new_callable=AsyncMock,
                side_effect=Exception("Key load failed"),
            ),
        ):
            options = await pool._build_ssh_options("host1", "user", str(key_file), opts)

        assert "client_keys" not in options

    @pytest.mark.asyncio
    async def test_build_options_without_username(self) -> None:
        """Test building SSH options without username."""
        pool = await SSHPool.get_instance()
        pool._auth_manager = None

        opts = SSHConnectionOptions()
        with patch.dict("os.environ", {"SSH_AUTH_SOCK": "/tmp/agent"}):
            options = await pool._build_ssh_options("host1", None, None, opts)

        assert "username" not in options


# ==============================================================================
# Tests for get_connection
# ==============================================================================


class TestSSHPoolGetConnection:
    """Tests for get_connection method."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_get_connection_reuses_alive(self) -> None:
        """Test that get_connection reuses alive connections."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        conn = SSHConnection(host="host1", connection=mock_conn)
        conn.is_alive = MagicMock(return_value=True)
        conn.refresh_timeout = MagicMock()

        pool._connections = {"user@host1:22": conn}

        result = await pool.get_connection("host1", username="user")

        assert result is conn
        conn.refresh_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_cleans_expired(self) -> None:
        """Test that get_connection cleans up expired connections."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        old_conn = SSHConnection(host="host1", connection=mock_conn)
        old_conn.is_alive = MagicMock(return_value=False)
        old_conn.close = AsyncMock()

        pool._connections = {"user@host1:22": old_conn}

        # Mock _create_connection to return new connection
        new_conn = SSHConnection(host="host1", connection=MagicMock())
        with patch.object(
            pool, "_create_connection", new_callable=AsyncMock, return_value=new_conn
        ):
            result = await pool.get_connection("host1", username="user")

        assert result is new_conn
        old_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connection_evicts_when_full(self) -> None:
        """Test that get_connection evicts LRU when pool is full."""
        from datetime import datetime, timedelta

        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance(max_connections=1)

        now = datetime.now(UTC)
        mock_conn = MagicMock()
        old_conn = SSHConnection(
            host="host1",
            connection=mock_conn,
            last_used=now - timedelta(hours=1),
        )
        old_conn.is_alive = MagicMock(return_value=True)
        old_conn.close = AsyncMock()

        pool._connections = {"user@host1:22": old_conn}

        new_conn = SSHConnection(host="host2", connection=MagicMock())
        with patch.object(
            pool, "_create_connection", new_callable=AsyncMock, return_value=new_conn
        ):
            await pool.get_connection("host2", username="admin")

        assert "user@host1:22" not in pool._connections
        assert "admin@host2:22" in pool._connections


# ==============================================================================
# Tests for _connect_with_options
# ==============================================================================


class TestSSHPoolConnectWithOptions:
    """Tests for _connect_with_options method."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_connect_success(self) -> None:
        """Test successful connection."""
        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        with patch("asyncssh.connect", new_callable=AsyncMock, return_value=mock_conn):
            result = await pool._connect_with_options(
                "host1",
                {"host": "host1", "port": 22},
                None,
                30,
            )

        assert result is mock_conn

    @pytest.mark.asyncio
    async def test_connect_permission_denied_retry_with_agent(self) -> None:
        """Test retry with agent on permission denied with client_keys."""
        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()

        call_count = [0]

        async def mock_connect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and "client_keys" in kwargs:
                raise asyncssh.PermissionDenied("Access denied")
            return mock_conn

        with patch("asyncssh.connect", side_effect=mock_connect):
            result = await pool._connect_with_options(
                "host1",
                {"host": "host1", "port": 22, "client_keys": ["key"]},
                None,
                30,
            )

        assert result is mock_conn
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_connect_permission_denied_no_retry_without_keys(self) -> None:
        """Test no retry on permission denied without client_keys."""
        pool = await SSHPool.get_instance()

        with patch(
            "asyncssh.connect",
            new_callable=AsyncMock,
            side_effect=asyncssh.PermissionDenied("Access denied"),
        ):
            with pytest.raises(asyncssh.PermissionDenied):
                await pool._connect_with_options(
                    "host1",
                    {"host": "host1", "port": 22},  # No client_keys
                    None,
                    30,
                )

    @pytest.mark.asyncio
    async def test_connect_permission_denied_keyboard_no_retry(self) -> None:
        """Test no retry on keyboard-interactive failure."""
        pool = await SSHPool.get_instance()

        with (
            patch(
                "asyncssh.connect",
                new_callable=AsyncMock,
                side_effect=asyncssh.PermissionDenied("keyboard-interactive failed"),
            ),
            pytest.raises(asyncssh.PermissionDenied),
        ):
            await pool._connect_with_options(
                "host1",
                {"host": "host1", "port": 22, "client_keys": ["key"]},
                None,
                30,
            )

    @pytest.mark.asyncio
    async def test_connect_removes_internal_keys(self) -> None:
        """Test that internal hint keys are removed before connecting."""
        pool = await SSHPool.get_instance()

        mock_conn = MagicMock()
        captured_kwargs = {}

        async def capture_connect(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_conn

        with patch("asyncssh.connect", side_effect=capture_connect):
            await pool._connect_with_options(
                "host1",
                {"host": "host1", "port": 22, "_internal_hint": "remove_me"},
                None,
                30,
            )

        assert "_internal_hint" not in captured_kwargs


# ==============================================================================
# Tests for execute
# ==============================================================================


class TestSSHPoolExecuteFlow:
    """Tests for full execute flow."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        """Test successful command execution."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_async_conn = MagicMock()
        mock_async_conn.run = AsyncMock(return_value=mock_result)

        conn = SSHConnection(host="host1", connection=mock_async_conn)
        conn.is_alive = MagicMock(return_value=True)
        conn.refresh_timeout = MagicMock()

        pool._connections = {"user@host1:22": conn}

        result = await pool.execute("host1", "ls -la", username="user")

        assert result.stdout == "output"
        assert result.stderr == ""
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_with_bytes_output(self) -> None:
        """Test execute handles bytes output."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_result = MagicMock()
        mock_result.stdout = b"binary output"
        mock_result.stderr = b"binary error"
        mock_result.exit_status = 0

        mock_async_conn = MagicMock()
        mock_async_conn.run = AsyncMock(return_value=mock_result)

        conn = SSHConnection(host="host1", connection=mock_async_conn)
        conn.is_alive = MagicMock(return_value=True)
        conn.refresh_timeout = MagicMock()

        pool._connections = {"user@host1:22": conn}

        result = await pool.execute("host1", "cat /bin/ls", username="user")

        assert result.stdout == "binary output"
        assert result.stderr == "binary error"

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        """Test execute handles timeout."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_async_conn = MagicMock()
        mock_async_conn.run = AsyncMock(side_effect=TimeoutError())

        conn = SSHConnection(host="host1", connection=mock_async_conn)
        conn.is_alive = MagicMock(return_value=True)
        conn.refresh_timeout = MagicMock()

        pool._connections = {"user@host1:22": conn}

        with pytest.raises(TimeoutError):
            await pool.execute("host1", "sleep 1000", username="user", timeout=1)

    @pytest.mark.asyncio
    async def test_execute_connection_closed(self) -> None:
        """Test execute raises when connection is closed."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        conn = SSHConnection(host="host1", connection=None)
        conn.is_alive = MagicMock(return_value=True)
        conn.refresh_timeout = MagicMock()

        pool._connections = {"user@host1:22": conn}

        with pytest.raises(RuntimeError, match="is closed"):
            await pool.execute("host1", "ls", username="user")

    @pytest.mark.asyncio
    async def test_execute_with_input_data(self) -> None:
        """Test execute with stdin input."""
        from merlya.ssh.types import SSHConnection

        pool = await SSHPool.get_instance()

        mock_result = MagicMock()
        mock_result.stdout = "processed input"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_async_conn = MagicMock()
        mock_async_conn.run = AsyncMock(return_value=mock_result)

        conn = SSHConnection(host="host1", connection=mock_async_conn)
        conn.is_alive = MagicMock(return_value=True)
        conn.refresh_timeout = MagicMock()

        pool._connections = {"user@host1:22": conn}

        result = await pool.execute("host1", "cat", username="user", input_data="hello")

        assert result.stdout == "processed input"
        mock_async_conn.run.assert_called_once_with("cat", input="hello")


# ==============================================================================
# Tests for _create_connection
# ==============================================================================


class TestSSHPoolCreateConnection:
    """Tests for _create_connection method."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_create_connection_with_tunnel(self) -> None:
        """Test connection creation with jump tunnel."""
        pool = await SSHPool.get_instance()

        mock_tunnel = MagicMock()
        mock_conn = MagicMock()

        with (
            patch.object(
                pool, "_build_ssh_options", new_callable=AsyncMock, return_value={"host": "host1"}
            ),
            patch.object(
                pool, "_setup_jump_tunnel", new_callable=AsyncMock, return_value=mock_tunnel
            ),
            patch.object(pool, "_create_mfa_client", return_value=None),
            patch.object(
                pool, "_connect_with_options", new_callable=AsyncMock, return_value=mock_conn
            ),
        ):
            result = await pool._create_connection(
                "host1",
                "user",
                None,
                SSHConnectionOptions(jump_host="jump.example.com"),
            )

        assert result.host == "host1"

    @pytest.mark.asyncio
    async def test_create_connection_cleans_tunnel_on_error(self) -> None:
        """Test tunnel cleanup on connection error."""
        pool = await SSHPool.get_instance()

        mock_tunnel = MagicMock()
        mock_tunnel.close = MagicMock()
        mock_tunnel.wait_closed = AsyncMock()

        with (
            patch.object(
                pool, "_build_ssh_options", new_callable=AsyncMock, return_value={"host": "host1"}
            ),
            patch.object(
                pool, "_setup_jump_tunnel", new_callable=AsyncMock, return_value=mock_tunnel
            ),
            patch.object(pool, "_create_mfa_client", return_value=None),
            patch.object(
                pool,
                "_connect_with_options",
                new_callable=AsyncMock,
                side_effect=asyncssh.ConnectionLost("Connection lost"),
            ),
        ):
            with pytest.raises(asyncssh.ConnectionLost):
                await pool._create_connection(
                    "host1",
                    "user",
                    None,
                    SSHConnectionOptions(jump_host="jump.example.com"),
                )

        mock_tunnel.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_connection_timeout_error(self) -> None:
        """Test connection timeout error handling."""
        pool = await SSHPool.get_instance()

        with (
            patch.object(
                pool, "_build_ssh_options", new_callable=AsyncMock, return_value={"host": "host1"}
            ),
            patch.object(pool, "_setup_jump_tunnel", new_callable=AsyncMock, return_value=None),
            patch.object(pool, "_create_mfa_client", return_value=None),
            patch.object(
                pool,
                "_connect_with_options",
                new_callable=AsyncMock,
                side_effect=TimeoutError(),
            ),
        ):
            with pytest.raises(TimeoutError):
                await pool._create_connection("host1", "user", None, SSHConnectionOptions())


# ==============================================================================
# Tests for _setup_jump_tunnel
# ==============================================================================


class TestSSHPoolSetupJumpTunnel:
    """Tests for _setup_jump_tunnel method."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_setup_jump_tunnel_with_credentials(self, tmp_path: Path) -> None:
        """Test jump tunnel setup with username and key."""
        pool = await SSHPool.get_instance()

        key_file = tmp_path / "jump_key"
        key_file.write_text("key content")

        mock_key = MagicMock()
        mock_tunnel = MagicMock()

        opts = SSHConnectionOptions(
            jump_host="jump.example.com",
            jump_port=2222,
            jump_username="jumpuser",
            jump_private_key=str(key_file),
        )

        with (
            patch.object(pool, "_load_jump_key", new_callable=AsyncMock, return_value=mock_key),
            patch(
                "asyncssh.connect", new_callable=AsyncMock, return_value=mock_tunnel
            ) as mock_connect,
        ):
            result = await pool._setup_jump_tunnel(opts)

        assert result is mock_tunnel
        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["host"] == "jump.example.com"
        assert call_kwargs["port"] == 2222
        assert call_kwargs["username"] == "jumpuser"
        assert call_kwargs["client_keys"] == [mock_key]


# ==============================================================================
# Tests for MFA Client Class
# ==============================================================================


class TestSSHPoolMFAClientClass:
    """Tests for the dynamically created MFA client class."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_mfa_client_kbdint_auth_requested(self) -> None:
        """Test MFA client kbdint_auth_requested returns empty string."""
        pool = await SSHPool.get_instance()
        pool._mfa_callback = lambda prompt: "code"

        client_class = pool._create_mfa_client()
        client = client_class()

        result = client.kbdint_auth_requested()

        assert result == ""

    @pytest.mark.asyncio
    async def test_mfa_client_kbdint_challenge_received(self) -> None:
        """Test MFA client handles challenge correctly."""

        def mfa_callback(prompt: str) -> str:
            return f"response_to_{prompt}"

        pool = await SSHPool.get_instance()
        pool._mfa_callback = mfa_callback

        client_class = pool._create_mfa_client()
        client = client_class()

        result = client.kbdint_challenge_received(
            "Authentication",
            "Please enter your code",
            "en-US",
            [("Enter OTP: ", False), ("Enter PIN: ", True)],
        )

        assert result == ["response_to_Enter OTP: ", "response_to_Enter PIN: "]
