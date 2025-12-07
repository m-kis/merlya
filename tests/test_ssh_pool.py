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
    async def test_passphrase_callback_used_on_keyimporterror(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Ensure KeyImportError triggers passphrase callback."""
        pool = await SSHPool.get_instance()
        pool._passphrase_callback = lambda _p: "secret-pass"

        key_file = tmp_path / "id_rsa"
        key_file.write_text("dummy")

        call_order: list[str] = []

        def fake_read_private_key(path: str, passphrase: str | None = None):
            if passphrase is None:
                call_order.append("first")
                raise asyncssh.KeyImportError("Passphrase must be specified to import encrypted private keys")
            call_order.append("second")
            return MagicMock()

        monkeypatch.setattr("asyncssh.read_private_key", fake_read_private_key)
        monkeypatch.setattr(Path, "exists", lambda self: True)

        key = await pool._load_private_key(key_file)

        assert call_order == ["first", "second"]
        assert key is not None
