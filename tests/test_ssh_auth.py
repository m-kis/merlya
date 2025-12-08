"""Tests for SSH authentication manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.ssh.auth import (
    SSHAuthManager,
    SSHAuthOptions,
    SSHEnvironment,
    detect_ssh_environment,
)


class TestSSHAuthManagerDefaultKeys:
    """Tests for SSHAuthManager default key discovery."""

    def test_find_default_keys_returns_existing(self, tmp_path: Path) -> None:
        """Test that _find_default_keys returns existing keys."""
        # Create mock secrets and ui
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        # Create a fake key
        fake_key = tmp_path / "id_ed25519"
        fake_key.touch()

        # Patch DEFAULT_KEY_PATHS to use our tmp path
        with patch.object(
            SSHAuthManager, "DEFAULT_KEY_PATHS", [str(fake_key), "~/.ssh/nonexistent"]
        ):
            keys = manager._find_default_keys()

        assert len(keys) == 1
        assert keys[0] == fake_key

    def test_find_default_keys_returns_empty_when_none_exist(self) -> None:
        """Test that _find_default_keys returns empty list when no keys exist."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        # Patch DEFAULT_KEY_PATHS to nonexistent paths
        with patch.object(
            SSHAuthManager,
            "DEFAULT_KEY_PATHS",
            ["/nonexistent/key1", "/nonexistent/key2"],
        ):
            keys = manager._find_default_keys()

        assert keys == []


class TestSSHAuthManagerPrepareAuth:
    """Tests for SSHAuthManager.prepare_auth with empty agent."""

    @pytest.mark.asyncio
    async def test_uses_default_key_when_agent_empty(self, tmp_path: Path) -> None:
        """Test that prepare_auth uses default keys when agent is empty."""
        # Create mock secrets and ui
        secrets = MagicMock()
        secrets.get.return_value = None
        secrets.has.return_value = False
        ui = MagicMock()
        ui.prompt_secret = AsyncMock(return_value=None)

        manager = SSHAuthManager(secrets, ui)

        # Create a fake key file
        fake_key = tmp_path / "id_ed25519"
        fake_key.write_text("fake key content")

        # Mock environment with agent available but empty
        empty_env = SSHEnvironment(
            agent_available=True,
            agent_socket="/tmp/ssh-agent.sock",
            agent_keys=[],  # No keys in agent
        )

        with (
            patch("merlya.ssh.auth.detect_ssh_environment", return_value=empty_env),
            patch.object(SSHAuthManager, "DEFAULT_KEY_PATHS", [str(fake_key)]),
            patch.object(manager, "_prepare_key_auth", new_callable=AsyncMock) as mock_prepare_key,
        ):
            await manager.prepare_auth(
                hostname="test.example.com",
                username="testuser",
                private_key=None,
            )

            # Should have called _prepare_key_auth with the default key
            mock_prepare_key.assert_called_once()
            call_args = mock_prepare_key.call_args
            assert str(fake_key) in call_args[0][0]

    @pytest.mark.asyncio
    async def test_uses_agent_when_keys_present(self) -> None:
        """Test that prepare_auth uses agent when it has keys."""
        from merlya.ssh.auth import AgentKeyInfo

        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        # Mock environment with agent and keys
        env_with_keys = SSHEnvironment(
            agent_available=True,
            agent_socket="/tmp/ssh-agent.sock",
            agent_keys=[
                AgentKeyInfo(
                    fingerprint="SHA256:xxx",
                    key_type="ed25519",
                    comment="test@example.com",
                )
            ],
        )

        with patch("merlya.ssh.auth.detect_ssh_environment", return_value=env_with_keys):
            options = await manager.prepare_auth(
                hostname="test.example.com",
                username="testuser",
                private_key=None,
            )

            # Should use agent path
            assert options.agent_path == "/tmp/ssh-agent.sock"
            assert options.client_keys is None

    @pytest.mark.asyncio
    async def test_falls_through_to_prompt_when_no_keys_anywhere(self) -> None:
        """Test that prepare_auth prompts user when agent empty and no default keys."""
        secrets = MagicMock()
        secrets.get.return_value = None
        secrets.has.return_value = False
        ui = MagicMock()
        ui.info = MagicMock()
        ui.prompt = AsyncMock(return_value="key")  # User chooses key auth
        ui.prompt_secret = AsyncMock(return_value=None)

        manager = SSHAuthManager(secrets, ui)

        # Mock environment with agent but empty
        empty_env = SSHEnvironment(
            agent_available=True,
            agent_socket="/tmp/ssh-agent.sock",
            agent_keys=[],
        )

        with (
            patch("merlya.ssh.auth.detect_ssh_environment", return_value=empty_env),
            patch.object(
                SSHAuthManager,
                "DEFAULT_KEY_PATHS",
                [],  # No default keys
            ),
        ):
            await manager.prepare_auth(
                hostname="test.example.com",
                username="testuser",
                private_key=None,
            )

            # Should have prompted user for auth method
            ui.info.assert_called()


class TestSSHAuthManagerLoadKey:
    """Tests for SSHAuthManager key loading with passphrase."""

    @pytest.mark.asyncio
    async def test_load_key_prompts_passphrase_on_encryption_error(self) -> None:
        """Test that _load_key_directly prompts for passphrase when key is encrypted."""
        import asyncssh

        secrets = MagicMock()
        secrets.set = MagicMock()
        ui = MagicMock()
        ui.prompt_secret = AsyncMock(return_value="test_passphrase")

        manager = SSHAuthManager(secrets, ui)
        options = SSHAuthOptions()

        fake_key = MagicMock()

        # First call raises KeyEncryptionError, second succeeds
        with patch(
            "asyncssh.read_private_key",
            side_effect=[asyncssh.KeyEncryptionError("encrypted"), fake_key],
        ):
            await manager._load_key_directly(Path("/fake/key"), None, options, "test_host")

        # Should have prompted for passphrase
        ui.prompt_secret.assert_called_once()
        # Should have stored the passphrase
        assert secrets.set.called

    @pytest.mark.asyncio
    async def test_load_key_stores_passphrase_in_keyring(self) -> None:
        """Test that successful passphrase is stored in keyring."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        await manager._store_passphrase(Path("/fake/key.pem"), "myhost", "secret123")

        # Should store with multiple cache keys
        assert secrets.set.call_count >= 2


class TestDetectSSHEnvironment:
    """Tests for detect_ssh_environment."""

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_socket(self) -> None:
        """Test returns unavailable when SSH_AUTH_SOCK not set."""
        with patch.dict("os.environ", {}, clear=True):
            env = await detect_ssh_environment()

        assert env.agent_available is False
        assert env.agent_socket is None

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_socket_missing(self, tmp_path: Path) -> None:
        """Test returns unavailable when socket file doesn't exist."""
        nonexistent = str(tmp_path / "nonexistent.sock")

        with patch.dict("os.environ", {"SSH_AUTH_SOCK": nonexistent}):
            env = await detect_ssh_environment()

        assert env.agent_available is False
