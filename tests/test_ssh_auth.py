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

    @pytest.mark.asyncio
    async def test_returns_available_with_keys(self, tmp_path: Path) -> None:
        """Test returns available with keys when agent exists."""
        from merlya.ssh.auth import AgentKeyInfo

        sock_path = tmp_path / "agent.sock"
        sock_path.touch()

        mock_keys = [
            AgentKeyInfo(
                fingerprint="SHA256:abc",
                key_type="ed25519",
                comment="test@example.com",
                bits=256,
            )
        ]

        with (
            patch.dict("os.environ", {"SSH_AUTH_SOCK": str(sock_path)}),
            patch(
                "merlya.ssh.auth._list_agent_keys", new_callable=AsyncMock, return_value=mock_keys
            ),
        ):
            env = await detect_ssh_environment()

        assert env.agent_available is True
        assert env.agent_socket == str(sock_path)
        assert len(env.agent_keys) == 1


# ==============================================================================
# Tests for _list_agent_keys
# ==============================================================================


class TestListAgentKeys:
    """Tests for _list_agent_keys function."""

    @pytest.mark.asyncio
    async def test_parses_ssh_add_output(self) -> None:
        """Test parsing of ssh-add -l output."""
        from merlya.ssh.auth import _list_agent_keys

        mock_output = (
            b"4096 SHA256:abcd1234 user@host (RSA)\n"
            b"256 SHA256:efgh5678 test@example.com (ED25519)\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(mock_output, b""))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            keys = await _list_agent_keys()

        assert len(keys) == 2
        assert keys[0].bits == 4096
        assert keys[0].fingerprint == "SHA256:abcd1234"
        assert keys[0].key_type == "rsa"
        assert keys[1].bits == 256
        assert keys[1].key_type == "ed25519"

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_identities(self) -> None:
        """Test returns empty list when no identities in agent."""
        from merlya.ssh.auth import _list_agent_keys

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"no identities"))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            keys = await _list_agent_keys()

        assert keys == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_command_not_found(self) -> None:
        """Test returns empty list when ssh-add not found."""
        from merlya.ssh.auth import _list_agent_keys

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError(),
        ):
            keys = await _list_agent_keys()

        assert keys == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        """Test returns empty list on general error."""
        from merlya.ssh.auth import _list_agent_keys

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=Exception("fail")
        ):
            keys = await _list_agent_keys()

        assert keys == []


# ==============================================================================
# Tests for key_in_agent
# ==============================================================================


class TestKeyInAgent:
    """Tests for key_in_agent function."""

    def test_finds_key_by_filename(self) -> None:
        """Test finding key by filename in comment."""
        from merlya.ssh.auth import AgentKeyInfo, key_in_agent

        agent_keys = [
            AgentKeyInfo(
                fingerprint="SHA256:xxx",
                key_type="ed25519",
                comment="/home/user/.ssh/id_ed25519",
            )
        ]

        assert key_in_agent("~/.ssh/id_ed25519", agent_keys) is True

    def test_finds_key_by_full_path(self) -> None:
        """Test finding key by full path in comment."""
        from merlya.ssh.auth import AgentKeyInfo, key_in_agent

        agent_keys = [
            AgentKeyInfo(
                fingerprint="SHA256:xxx",
                key_type="rsa",
                comment="/Users/test/.ssh/id_rsa",
            )
        ]

        assert key_in_agent("/Users/test/.ssh/id_rsa", agent_keys) is True

    def test_returns_false_when_not_found(self) -> None:
        """Test returns False when key not in agent."""
        from merlya.ssh.auth import AgentKeyInfo, key_in_agent

        agent_keys = [
            AgentKeyInfo(
                fingerprint="SHA256:xxx",
                key_type="ed25519",
                comment="other@host",
            )
        ]

        assert key_in_agent("~/.ssh/id_rsa", agent_keys) is False


# ==============================================================================
# Tests for ManagedSSHAgent
# ==============================================================================


class TestManagedSSHAgent:
    """Tests for ManagedSSHAgent class."""

    @pytest.mark.asyncio
    async def test_get_instance_singleton(self) -> None:
        """Test get_instance returns singleton."""
        from merlya.ssh.auth import ManagedSSHAgent

        # Reset singleton
        ManagedSSHAgent._instance = None

        agent1 = await ManagedSSHAgent.get_instance()
        agent2 = await ManagedSSHAgent.get_instance()

        assert agent1 is agent2

        # Cleanup
        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_ensure_agent_running_uses_existing(self) -> None:
        """Test ensure_agent_running uses existing agent."""
        from merlya.ssh.auth import ManagedSSHAgent, SSHEnvironment

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        existing_env = SSHEnvironment(
            agent_available=True,
            agent_socket="/tmp/existing.sock",
            agent_keys=[],
        )

        with patch(
            "merlya.ssh.auth.detect_ssh_environment",
            new_callable=AsyncMock,
            return_value=existing_env,
        ):
            result = await agent.ensure_agent_running()

        assert result is True
        assert agent.agent_sock == "/tmp/existing.sock"

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_start_agent_parses_output(self) -> None:
        """Test _start_agent parses ssh-agent output correctly."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        mock_output = b"SSH_AUTH_SOCK=/tmp/ssh-abc123/agent.sock; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=12345; export SSH_AGENT_PID;\n"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(mock_output, b""))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            result = await agent._start_agent()

        assert result is True
        assert agent.agent_sock == "/tmp/ssh-abc123/agent.sock"
        assert agent.agent_pid == 12345

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_start_agent_fails_gracefully(self) -> None:
        """Test _start_agent handles failures."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            result = await agent._start_agent()

        assert result is False

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_start_agent_command_not_found(self) -> None:
        """Test _start_agent handles command not found."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError(),
        ):
            result = await agent._start_agent()

        assert result is False

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_add_key_file_not_found(self) -> None:
        """Test add_key returns False for non-existent file."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        result = await agent.add_key("/nonexistent/key")

        assert result is False

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_add_key_direct_success(self, tmp_path: Path) -> None:
        """Test adding unencrypted key directly."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        key_file = tmp_path / "id_rsa"
        key_file.write_text("fake key")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Identity added", b""))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            result = await agent._add_key_direct(str(key_file))

        assert result is True

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_add_key_direct_needs_passphrase(self, tmp_path: Path) -> None:
        """Test add_key_direct returns False when passphrase needed."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted key")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Enter passphrase"))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            result = await agent._add_key_direct(str(key_file))

        assert result is False

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_add_key_with_passphrase(self, tmp_path: Path) -> None:
        """Test adding encrypted key with passphrase."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted key")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Identity added", b""))

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc
        ):
            result = await agent._add_key_with_passphrase(str(key_file), "secret123")

        assert result is True

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_cleanup_stops_managed_agent(self) -> None:
        """Test cleanup stops the managed agent."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()
        agent.agent_pid = 12345
        agent.agent_sock = "/tmp/agent.sock"

        with patch("os.kill") as mock_kill:
            await agent.cleanup()

        mock_kill.assert_called_once()
        assert agent.agent_pid is None
        assert agent.agent_sock is None

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_cleanup_handles_process_not_found(self) -> None:
        """Test cleanup handles ProcessLookupError gracefully."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()
        agent.agent_pid = 12345

        with patch("os.kill", side_effect=ProcessLookupError()):
            await agent.cleanup()  # Should not raise

        assert agent.agent_pid is None

        ManagedSSHAgent._instance = None

    @pytest.mark.asyncio
    async def test_cleanup_restores_original_env(self) -> None:
        """Test cleanup restores original environment variables."""
        from merlya.ssh.auth import ManagedSSHAgent

        ManagedSSHAgent._instance = None
        agent = await ManagedSSHAgent.get_instance()
        agent.agent_pid = 12345
        agent._original_sock = "/original/sock"
        agent._original_pid = "99999"

        import os

        os.environ["SSH_AUTH_SOCK"] = "/tmp/managed"
        os.environ["SSH_AGENT_PID"] = "12345"

        with patch("os.kill"):
            await agent.cleanup()

        assert os.environ.get("SSH_AUTH_SOCK") == "/original/sock"
        assert os.environ.get("SSH_AGENT_PID") == "99999"

        ManagedSSHAgent._instance = None


# ==============================================================================
# Tests for SSHAuthManager additional methods
# ==============================================================================


class TestSSHAuthManagerMFA:
    """Tests for SSHAuthManager MFA callback."""

    def test_set_mfa_callback(self) -> None:
        """Test setting MFA callback."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        def callback(prompt):
            return "123456"

        manager.set_mfa_callback(callback)

        assert manager._mfa_callback is callback


class TestSSHAuthManagerKeyEncryption:
    """Tests for key encryption detection."""

    def test_key_is_encrypted_returns_false_for_unencrypted(self, tmp_path: Path) -> None:
        """Test _key_is_encrypted returns False for unencrypted key."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("unencrypted")

        with patch("asyncssh.read_private_key", return_value=MagicMock()):
            result = manager._key_is_encrypted(key_file)

        assert result is False

    def test_key_is_encrypted_returns_true_on_error(self, tmp_path: Path) -> None:
        """Test _key_is_encrypted returns True when key read fails."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        with patch("asyncssh.read_private_key", side_effect=Exception("encrypted")):
            result = manager._key_is_encrypted(key_file)

        assert result is True


class TestSSHAuthManagerPasswordAuth:
    """Tests for password authentication."""

    @pytest.mark.asyncio
    async def test_prepare_password_auth_uses_cached(self) -> None:
        """Test _prepare_password_auth uses cached password."""
        secrets = MagicMock()
        secrets.get.return_value = "cached_password"
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        options = SSHAuthOptions()
        await manager._prepare_password_auth("host1", "user", "host1.example.com", options)

        assert options.password == "cached_password"
        assert options.preferred_auth == "password,keyboard-interactive"

    @pytest.mark.asyncio
    async def test_prepare_password_auth_prompts_user(self) -> None:
        """Test _prepare_password_auth prompts for password."""
        secrets = MagicMock()
        secrets.get.return_value = None
        ui = MagicMock()
        ui.prompt_secret = AsyncMock(return_value="user_password")
        manager = SSHAuthManager(secrets, ui)

        options = SSHAuthOptions()
        await manager._prepare_password_auth("host1", "testuser", "host1.example.com", options)

        assert options.password == "user_password"
        ui.prompt_secret.assert_called_once()
        secrets.set.assert_called()

    @pytest.mark.asyncio
    async def test_has_stored_password(self) -> None:
        """Test _has_stored_password checks secrets store."""
        secrets = MagicMock()
        secrets.has.return_value = True
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        result = await manager._has_stored_password("host1")

        assert result is True
        secrets.has.assert_called_with("ssh:password:host1")


class TestSSHAuthManagerPrompts:
    """Tests for user prompts."""

    @pytest.mark.asyncio
    async def test_prompt_auth_method_returns_password(self) -> None:
        """Test _prompt_auth_method returns password when selected."""
        secrets = MagicMock()
        ui = MagicMock()
        ui.prompt = AsyncMock(return_value="password")
        ui.info = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        result = await manager._prompt_auth_method("host.example.com", "user")

        assert result == "password"
        ui.info.assert_called()

    @pytest.mark.asyncio
    async def test_prompt_auth_method_returns_key_default(self) -> None:
        """Test _prompt_auth_method returns key by default."""
        secrets = MagicMock()
        ui = MagicMock()
        ui.prompt = AsyncMock(return_value="key")
        ui.info = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        result = await manager._prompt_auth_method("host.example.com", None)

        assert result == "key"

    @pytest.mark.asyncio
    async def test_prompt_key_path_with_existing_default(self, tmp_path: Path) -> None:
        """Test _prompt_key_path returns existing default key."""
        secrets = MagicMock()
        ui = MagicMock()
        ui.prompt = AsyncMock(return_value=str(tmp_path / "id_ed25519"))
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_ed25519"
        key_file.write_text("key content")

        with patch.object(Path, "expanduser", return_value=key_file):
            result = await manager._prompt_key_path()

        assert result is not None

    @pytest.mark.asyncio
    async def test_prompt_key_path_file_not_found(self) -> None:
        """Test _prompt_key_path shows error for non-existent file."""
        secrets = MagicMock()
        ui = MagicMock()
        ui.prompt = AsyncMock(return_value="/nonexistent/key")
        ui.error = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        result = await manager._prompt_key_path()

        assert result is None
        ui.error.assert_called()

    @pytest.mark.asyncio
    async def test_prompt_key_path_empty_response(self) -> None:
        """Test _prompt_key_path handles empty response."""
        secrets = MagicMock()
        ui = MagicMock()
        ui.prompt = AsyncMock(return_value="")
        manager = SSHAuthManager(secrets, ui)

        result = await manager._prompt_key_path()

        assert result is None


class TestSSHAuthManagerGetPassphrase:
    """Tests for passphrase retrieval."""

    @pytest.mark.asyncio
    async def test_get_passphrase_returns_none_for_unencrypted(self, tmp_path: Path) -> None:
        """Test _get_passphrase returns None for unencrypted key."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("unencrypted")

        with patch.object(manager, "_key_is_encrypted", return_value=False):
            result = await manager._get_passphrase(key_file, "host1")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_passphrase_uses_cache(self, tmp_path: Path) -> None:
        """Test _get_passphrase uses cached passphrase."""
        secrets = MagicMock()
        secrets.get.return_value = "cached_passphrase"
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        with patch.object(manager, "_key_is_encrypted", return_value=True):
            result = await manager._get_passphrase(key_file, "host1")

        assert result == "cached_passphrase"

    @pytest.mark.asyncio
    async def test_get_passphrase_returns_none_when_not_cached(self, tmp_path: Path) -> None:
        """Test _get_passphrase returns None when no cached passphrase.

        Note: Passphrase prompting now happens in _load_key_directly, not in _get_passphrase.
        """
        secrets = MagicMock()
        secrets.get.return_value = None
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        with patch.object(manager, "_key_is_encrypted", return_value=True):
            result = await manager._get_passphrase(key_file, "host1")

        # No cached passphrase, returns None (prompting happens elsewhere)
        assert result is None
        assert not secrets.set.called


class TestSSHAuthManagerCleanup:
    """Tests for cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_with_managed_agent(self) -> None:
        """Test cleanup cleans up managed agent."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        mock_agent = MagicMock()
        mock_agent.cleanup = AsyncMock()
        manager._managed_agent = mock_agent

        await manager.cleanup()

        mock_agent.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_without_managed_agent(self) -> None:
        """Test cleanup does nothing without managed agent."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)
        manager._managed_agent = None

        await manager.cleanup()  # Should not raise


class TestSSHAuthManagerPrepareKeyAuth:
    """Tests for _prepare_key_auth method."""

    @pytest.mark.asyncio
    async def test_prepare_key_auth_nonexistent_key(self) -> None:
        """Test _prepare_key_auth handles non-existent key."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        options = SSHAuthOptions()
        await manager._prepare_key_auth("/nonexistent/key", "host1", options)

        # Should not have loaded any keys
        assert options.client_keys is None


class TestSSHAuthManagerLoadKeyDirectly:
    """Tests for _load_key_directly method."""

    @pytest.mark.asyncio
    async def test_load_key_directly_success(self, tmp_path: Path) -> None:
        """Test successful key loading."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("key content")

        mock_key = MagicMock()
        options = SSHAuthOptions()

        with patch("asyncssh.read_private_key", return_value=mock_key):
            await manager._load_key_directly(key_file, None, options)

        assert options.client_keys == [mock_key]

    @pytest.mark.asyncio
    async def test_load_key_directly_key_import_error_passphrase(self, tmp_path: Path) -> None:
        """Test _load_key_directly handles KeyImportError with passphrase prompt."""
        import asyncssh

        secrets = MagicMock()
        secrets.set = MagicMock()
        ui = MagicMock()
        ui.prompt_secret = AsyncMock(return_value="test_passphrase")
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        mock_key = MagicMock()
        options = SSHAuthOptions()

        # First call raises KeyImportError with passphrase message, second succeeds
        with patch(
            "asyncssh.read_private_key",
            side_effect=[asyncssh.KeyImportError("passphrase required"), mock_key],
        ):
            await manager._load_key_directly(key_file, None, options, "host1")

        assert options.client_keys == [mock_key]

    @pytest.mark.asyncio
    async def test_load_key_directly_key_import_error_invalid(self, tmp_path: Path) -> None:
        """Test _load_key_directly handles KeyImportError without passphrase message."""
        import asyncssh

        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("invalid key")

        options = SSHAuthOptions()

        with patch(
            "asyncssh.read_private_key", side_effect=asyncssh.KeyImportError("invalid format")
        ):
            await manager._load_key_directly(key_file, None, options)

        # Key should not be loaded
        assert options.client_keys is None

    @pytest.mark.asyncio
    async def test_load_key_directly_general_error(self, tmp_path: Path) -> None:
        """Test _load_key_directly handles general exceptions."""
        secrets = MagicMock()
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("bad key")

        options = SSHAuthOptions()

        with patch("asyncssh.read_private_key", side_effect=Exception("Unknown error")):
            await manager._load_key_directly(key_file, None, options)

        assert options.client_keys is None

    @pytest.mark.asyncio
    async def test_load_key_directly_user_cancels_passphrase(self, tmp_path: Path) -> None:
        """Test _load_key_directly when user cancels passphrase prompt."""
        import asyncssh

        secrets = MagicMock()
        ui = MagicMock()
        ui.prompt_secret = AsyncMock(return_value=None)  # User cancels
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        options = SSHAuthOptions()

        with patch(
            "asyncssh.read_private_key", side_effect=asyncssh.KeyEncryptionError("encrypted")
        ):
            await manager._load_key_directly(key_file, None, options)

        assert options.client_keys is None

    @pytest.mark.asyncio
    async def test_load_key_directly_retries_on_wrong_passphrase(self, tmp_path: Path) -> None:
        """Test _load_key_directly retries up to 3 times with wrong passphrase."""
        import asyncssh

        secrets = MagicMock()
        secrets.delete = MagicMock()
        ui = MagicMock()
        ui.error = MagicMock()
        # Provide 2 passphrases: wrong1, then correct
        # Flow: attempt 0 (no pass) → prompt → wrong1
        #       attempt 1 (wrong1) → error shown → prompt → correct
        #       attempt 2 (correct) → success
        ui.prompt_secret = AsyncMock(side_effect=["wrong1", "correct"])
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        mock_key = MagicMock()
        options = SSHAuthOptions()

        # 3 calls: fail on None, fail on wrong1, succeed on correct
        with patch(
            "asyncssh.read_private_key",
            side_effect=[
                asyncssh.KeyEncryptionError("Unable to decrypt"),  # No passphrase
                asyncssh.KeyEncryptionError("Unable to decrypt"),  # wrong1
                mock_key,  # correct
            ],
        ):
            await manager._load_key_directly(key_file, None, options, "host1")

        # Should have loaded the key after retry
        assert options.client_keys == [mock_key]
        # Error shown once for wrong passphrase (after wrong1)
        assert ui.error.call_count == 1

    @pytest.mark.asyncio
    async def test_load_key_directly_max_retries_reached(self, tmp_path: Path) -> None:
        """Test _load_key_directly fails after 3 attempts."""
        import asyncssh

        secrets = MagicMock()
        secrets.delete = MagicMock()
        ui = MagicMock()
        ui.error = MagicMock()
        # Provide passphrases that are always wrong
        # Flow: attempt 0 (no pass) → prompt → wrong1
        #       attempt 1 (wrong1) → error shown → prompt → wrong2
        #       attempt 2 (wrong2) → error "max attempts reached"
        ui.prompt_secret = AsyncMock(side_effect=["wrong1", "wrong2"])
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        options = SSHAuthOptions()

        with patch(
            "asyncssh.read_private_key",
            side_effect=asyncssh.KeyEncryptionError("Unable to decrypt"),
        ):
            await manager._load_key_directly(key_file, None, options, "host1")

        # Key should not be loaded
        assert options.client_keys is None
        # 2 errors: 1 "Wrong passphrase" (after wrong1), 1 "Max attempts reached" (after wrong2)
        assert ui.error.call_count == 2
        # Wrong passphrase should be cleared from cache
        assert secrets.delete.called

    @pytest.mark.asyncio
    async def test_load_key_directly_clears_wrong_cached_passphrase(self, tmp_path: Path) -> None:
        """Test _load_key_directly clears wrong cached passphrase."""
        import asyncssh

        secrets = MagicMock()
        secrets.delete = MagicMock()
        ui = MagicMock()
        ui.error = MagicMock()
        ui.prompt_secret = AsyncMock(return_value="correct")
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "id_rsa"
        key_file.write_text("encrypted")

        mock_key = MagicMock()
        options = SSHAuthOptions()

        # First call with cached passphrase fails, then user provides correct one
        with patch(
            "asyncssh.read_private_key",
            side_effect=[
                asyncssh.KeyEncryptionError("Unable to decrypt"),  # wrong cached
                mock_key,  # user's correct passphrase
            ],
        ):
            await manager._load_key_directly(key_file, "wrong_cached", options, "host1")

        # Key should be loaded
        assert options.client_keys == [mock_key]
        # Wrong cached passphrase should be cleared
        assert secrets.delete.called


class TestSSHAuthManagerPrepareAuthEdgeCases:
    """Tests for prepare_auth edge cases."""

    @pytest.mark.asyncio
    async def test_prepare_auth_with_private_key(self, tmp_path: Path) -> None:
        """Test prepare_auth when private_key is provided."""
        secrets = MagicMock()
        secrets.get.return_value = None
        ui = MagicMock()
        ui.prompt_secret = AsyncMock(return_value=None)
        manager = SSHAuthManager(secrets, ui)

        key_file = tmp_path / "custom_key"
        key_file.write_text("key content")

        mock_key = MagicMock()

        with patch("asyncssh.read_private_key", return_value=mock_key):
            options = await manager.prepare_auth(
                hostname="host.example.com",
                username="user",
                private_key=str(key_file),
            )

        assert options.client_keys == [mock_key]

    @pytest.mark.asyncio
    async def test_prepare_auth_uses_stored_password(self) -> None:
        """Test prepare_auth uses stored password when available."""
        secrets = MagicMock()
        secrets.has.return_value = True
        secrets.get.return_value = "stored_password"
        ui = MagicMock()
        manager = SSHAuthManager(secrets, ui)

        # No agent, no private key, but stored password
        no_agent_env = SSHEnvironment(
            agent_available=False,
            agent_socket=None,
        )

        with patch(
            "merlya.ssh.auth.detect_ssh_environment",
            new_callable=AsyncMock,
            return_value=no_agent_env,
        ):
            options = await manager.prepare_auth(
                hostname="host.example.com",
                username="user",
                private_key=None,
            )

        assert options.password == "stored_password"
        assert "password" in options.preferred_auth

    @pytest.mark.asyncio
    async def test_prepare_auth_prompts_for_password(self) -> None:
        """Test prepare_auth prompts for password when chosen."""
        secrets = MagicMock()
        secrets.has.return_value = False
        secrets.get.return_value = None
        ui = MagicMock()
        ui.info = MagicMock()
        ui.prompt = AsyncMock(return_value="password")  # User chooses password
        ui.prompt_secret = AsyncMock(return_value="user_password")
        manager = SSHAuthManager(secrets, ui)

        no_agent_env = SSHEnvironment(
            agent_available=False,
            agent_socket=None,
        )

        with patch(
            "merlya.ssh.auth.detect_ssh_environment",
            new_callable=AsyncMock,
            return_value=no_agent_env,
        ):
            options = await manager.prepare_auth(
                hostname="host.example.com",
                username="user",
                private_key=None,
            )

        assert options.password == "user_password"

    @pytest.mark.asyncio
    async def test_prepare_auth_uses_agent_fallback(self) -> None:
        """Test prepare_auth falls back to agent when user doesn't provide key."""
        secrets = MagicMock()
        secrets.has.return_value = False
        secrets.get.return_value = None
        ui = MagicMock()
        ui.info = MagicMock()
        ui.prompt = AsyncMock(return_value="key")
        ui.prompt_secret = AsyncMock(return_value=None)
        manager = SSHAuthManager(secrets, ui)

        no_agent_env = SSHEnvironment(
            agent_available=False,
            agent_socket=None,
        )

        with (
            patch(
                "merlya.ssh.auth.detect_ssh_environment",
                new_callable=AsyncMock,
                return_value=no_agent_env,
            ),
            patch.object(manager, "_prompt_key_path", new_callable=AsyncMock, return_value=None),
            patch.dict("os.environ", {"SSH_AUTH_SOCK": "/fallback/agent.sock"}),
        ):
            options = await manager.prepare_auth(
                hostname="host.example.com",
                username="user",
                private_key=None,
            )

        assert options.agent_path == "/fallback/agent.sock"
