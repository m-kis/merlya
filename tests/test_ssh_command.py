"""
Tests for the centralized /ssh command handler.

Tests:
- SSH overview display
- Key listing
- Agent status
- Global key management (set, show, clear)
- Per-host key management
- Passphrase handling
- Connection testing
"""
from unittest.mock import MagicMock, patch

import pytest

from merlya.repl.commands.ssh import SSHCommandHandler, agent, hosts, keys, passphrase, test
from merlya.security.credentials import CredentialManager, VariableType


@pytest.fixture
def mock_repl():
    """Create a mock REPL instance."""
    repl = MagicMock()
    repl.credentials = CredentialManager(storage_manager=None)
    repl.credential_manager = repl.credentials
    return repl


@pytest.fixture
def ssh_handler(mock_repl):
    """Create SSH command handler with mock REPL."""
    return SSHCommandHandler(repl=mock_repl)


@pytest.fixture
def mock_ssh_key(tmp_path):
    """Create a mock unencrypted SSH key file."""
    key_content = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBbT3bKV3gG9qnHKCJbzKKWwQgAAAAEbm9uZQAAAAAAAAAB
-----END OPENSSH PRIVATE KEY-----
"""
    key_path = tmp_path / "id_test"
    key_path.write_text(key_content)
    return str(key_path)


class TestSSHCommandHandling:
    """Tests for SSH command routing and basic handling."""

    def test_handle_no_args_shows_overview(self, ssh_handler):
        """Test: /ssh without args shows overview."""
        with patch('merlya.repl.commands.ssh.keys.show_overview', return_value=True) as mock:
            result = ssh_handler.handle([])
            mock.assert_called_once()
            assert result is True

    def test_handle_info_shows_overview(self, ssh_handler):
        """Test: /ssh info shows overview."""
        with patch('merlya.repl.commands.ssh.keys.show_overview', return_value=True) as mock:
            result = ssh_handler.handle(['info'])
            mock.assert_called_once()
            assert result is True

    def test_handle_keys_shows_keys(self, ssh_handler):
        """Test: /ssh keys shows key list."""
        with patch('merlya.repl.commands.ssh.keys.show_keys', return_value=True) as mock:
            result = ssh_handler.handle(['keys'])
            mock.assert_called_once()
            assert result is True

    def test_handle_agent_shows_agent(self, ssh_handler):
        """Test: /ssh agent shows agent status."""
        with patch('merlya.repl.commands.ssh.agent.show_agent', return_value=True) as mock:
            result = ssh_handler.handle(['agent'])
            mock.assert_called_once()
            assert result is True

    def test_handle_help_shows_help(self, ssh_handler):
        """Test: /ssh help shows help."""
        with patch.object(ssh_handler, '_show_help', return_value=True) as mock:
            result = ssh_handler.handle(['help'])
            mock.assert_called_once()
            assert result is True

    def test_handle_unknown_command(self, ssh_handler, capsys):
        """Test: Unknown subcommand shows error and help."""
        with patch.object(ssh_handler, '_show_help'):
            result = ssh_handler.handle(['unknown'])
            assert result is True


class TestGlobalKeyManagement:
    """Tests for global SSH key management."""

    def test_set_global_key(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: /ssh key set <path> sets global key."""
        # Mock path validation to allow temp files
        with patch(
            'merlya.repl.commands.ssh.keys.validate_ssh_key_path',
            return_value=(True, mock_ssh_key, None)
        ):
            with patch('builtins.input', return_value='n'):  # Skip passphrase prompt
                result = keys.set_global_key(ssh_handler, [mock_ssh_key])

        assert result is True
        assert mock_repl.credential_manager.get_variable("ssh_key_global") == mock_ssh_key

    def test_set_global_key_missing_path(self, ssh_handler, capsys):
        """Test: /ssh key set without path shows error."""
        result = keys.set_global_key(ssh_handler, [])
        assert result is True
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_set_global_key_file_not_found(self, ssh_handler, capsys):
        """Test: /ssh key set with nonexistent file shows error."""
        result = keys.set_global_key(ssh_handler, ['/nonexistent/path/key'])
        assert result is True
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_clear_global_key(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: /ssh key clear removes global key."""
        # First set a key
        mock_repl.credential_manager.set_variable(
            "ssh_key_global", mock_ssh_key, VariableType.CONFIG
        )
        mock_repl.credential_manager.set_variable(
            "ssh-passphrase-global", "secret", VariableType.SECRET
        )

        result = keys.clear_global_key(ssh_handler)

        assert result is True
        assert mock_repl.credential_manager.get_variable("ssh_key_global") is None
        assert mock_repl.credential_manager.get_variable("ssh-passphrase-global") is None

    def test_show_global_key(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: /ssh key show displays global key config."""
        mock_repl.credential_manager.set_variable(
            "ssh_key_global", mock_ssh_key, VariableType.CONFIG
        )

        result = keys.show_global_key(ssh_handler)
        assert result is True


class TestHostKeyManagement:
    """Tests for per-host SSH key management."""

    def test_show_host_config_host_not_found(self, ssh_handler, capsys):
        """Test: /ssh host <name> show with unknown host shows warning."""
        ssh_handler._repo = MagicMock()
        ssh_handler._repo.get_host_by_name.return_value = None

        result = hosts.show_host_config(ssh_handler, "unknown-host")

        assert result is True
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_show_host_config_with_key(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: /ssh host <name> show displays host SSH config."""
        ssh_handler._repo = MagicMock()
        ssh_handler._repo.get_host_by_name.return_value = {
            "hostname": "web-prod-01",
            "metadata": {
                "ssh_key_path": mock_ssh_key,
                "ssh_passphrase_secret": "ssh-passphrase-web-prod-01"
            }
        }

        result = hosts.show_host_config(ssh_handler, "web-prod-01")
        assert result is True

    def test_clear_host_config(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: /ssh host <name> clear removes host SSH config."""
        ssh_handler._repo = MagicMock()
        ssh_handler._repo.get_host_by_name.return_value = {
            "hostname": "web-prod-01",
            "metadata": {
                "ssh_key_path": mock_ssh_key,
                "ssh_passphrase_secret": "ssh-passphrase-web-prod-01"
            }
        }

        mock_repl.credential_manager.set_variable(
            "ssh-passphrase-web-prod-01", "secret", VariableType.SECRET
        )

        result = hosts.clear_host_config(ssh_handler, "web-prod-01")

        assert result is True
        ssh_handler._repo.add_host.assert_called_once()
        # Check metadata was cleared
        call_kwargs = ssh_handler._repo.add_host.call_args[1]
        assert "ssh_key_path" not in call_kwargs.get("metadata", {})


class TestPassphraseManagement:
    """Tests for passphrase caching."""

    def test_passphrase_for_global(self, ssh_handler, mock_repl):
        """Test: /ssh passphrase global caches global passphrase."""
        with patch('getpass.getpass', return_value='my-passphrase'):
            result = passphrase.handle_passphrase(ssh_handler, ['global'])

        assert result is True
        assert mock_repl.credential_manager.get_variable("ssh-passphrase-global") == "my-passphrase"

    def test_passphrase_for_key_name(self, ssh_handler, mock_repl):
        """Test: /ssh passphrase <key_name> caches passphrase."""
        with patch('getpass.getpass', return_value='key-passphrase'):
            result = passphrase.handle_passphrase(ssh_handler, ['id_ed25519'])

        assert result is True
        assert mock_repl.credential_manager.get_variable("ssh-passphrase-id_ed25519") == "key-passphrase"

    def test_passphrase_empty_skipped(self, ssh_handler, mock_repl, capsys):
        """Test: Empty passphrase is not saved."""
        with patch('getpass.getpass', return_value=''):
            result = passphrase.handle_passphrase(ssh_handler, ['id_rsa'])

        assert result is True
        assert mock_repl.credential_manager.get_variable("ssh-passphrase-id_rsa") is None
        captured = capsys.readouterr()
        assert "Empty passphrase" in captured.out

    def test_passphrase_no_args(self, ssh_handler, capsys):
        """Test: /ssh passphrase without args shows usage."""
        result = passphrase.handle_passphrase(ssh_handler, [])
        assert result is True
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestConnectionTesting:
    """Tests for SSH connection testing."""

    def test_test_no_hostname(self, ssh_handler, capsys):
        """Test: /ssh test without hostname shows error."""
        result = test.handle_test(ssh_handler, [])
        assert result is True
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_test_connection_success(self, ssh_handler, mock_repl):
        """Test: /ssh test <hostname> with successful connection."""
        with patch('merlya.executors.ssh.SSHManager') as mock_ssh:
            mock_instance = MagicMock()
            mock_instance.test_connection.return_value = True
            mock_ssh.return_value = mock_instance

            with patch.object(
                mock_repl.credentials, 'resolve_ssh_for_host',
                return_value=('/path/to/key', None, 'default')
            ):
                result = test.handle_test(ssh_handler, ['web-prod-01'])

        assert result is True

    def test_test_connection_failure(self, ssh_handler, mock_repl):
        """Test: /ssh test <hostname> with failed connection."""
        with patch('merlya.executors.ssh.SSHManager') as mock_ssh:
            mock_instance = MagicMock()
            mock_instance.test_connection.return_value = False
            mock_ssh.return_value = mock_instance

            with patch.object(
                mock_repl.credentials, 'resolve_ssh_for_host',
                return_value=('/path/to/key', None, 'default')
            ):
                result = test.handle_test(ssh_handler, ['web-prod-01'])

        assert result is True


class TestKeySubcommand:
    """Tests for /ssh key subcommand routing."""

    def test_key_no_args_shows_global(self, ssh_handler):
        """Test: /ssh key without args shows global config."""
        with patch('merlya.repl.commands.ssh.keys.show_global_key', return_value=True) as mock:
            result = keys.handle_key(ssh_handler, [])
            mock.assert_called_once()
            assert result is True

    def test_key_show(self, ssh_handler):
        """Test: /ssh key show shows global config."""
        with patch('merlya.repl.commands.ssh.keys.show_global_key', return_value=True) as mock:
            result = keys.handle_key(ssh_handler, ['show'])
            mock.assert_called_once()
            assert result is True

    def test_key_set(self, ssh_handler):
        """Test: /ssh key set routes to set function."""
        with patch('merlya.repl.commands.ssh.keys.set_global_key', return_value=True) as mock:
            result = keys.handle_key(ssh_handler, ['set', '/path/to/key'])
            mock.assert_called_once_with(ssh_handler, ['/path/to/key'])
            assert result is True

    def test_key_clear(self, ssh_handler):
        """Test: /ssh key clear routes to clear function."""
        with patch('merlya.repl.commands.ssh.keys.clear_global_key', return_value=True) as mock:
            result = keys.handle_key(ssh_handler, ['clear'])
            mock.assert_called_once()
            assert result is True

    def test_key_path_directly(self, ssh_handler):
        """Test: /ssh key <path> sets key directly."""
        with patch('merlya.repl.commands.ssh.keys.set_global_key', return_value=True) as mock:
            result = keys.handle_key(ssh_handler, ['/path/to/key'])
            mock.assert_called_once_with(ssh_handler, ['/path/to/key'])
            assert result is True


class TestHostSubcommand:
    """Tests for /ssh host subcommand routing."""

    def test_host_no_args(self, ssh_handler, capsys):
        """Test: /ssh host without args shows error."""
        result = hosts.handle_host(ssh_handler, [])
        assert result is True
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_host_show_default(self, ssh_handler):
        """Test: /ssh host <name> defaults to show."""
        with patch('merlya.repl.commands.ssh.hosts.show_host_config', return_value=True) as mock:
            result = hosts.handle_host(ssh_handler, ['web-prod-01'])
            mock.assert_called_once_with(ssh_handler, 'web-prod-01')
            assert result is True

    def test_host_show_explicit(self, ssh_handler):
        """Test: /ssh host <name> show routes correctly."""
        with patch('merlya.repl.commands.ssh.hosts.show_host_config', return_value=True) as mock:
            result = hosts.handle_host(ssh_handler, ['web-prod-01', 'show'])
            mock.assert_called_once_with(ssh_handler, 'web-prod-01')
            assert result is True

    def test_host_set(self, ssh_handler):
        """Test: /ssh host <name> set routes correctly."""
        with patch('merlya.repl.commands.ssh.hosts.set_host_key', return_value=True) as mock:
            result = hosts.handle_host(ssh_handler, ['web-prod-01', 'set'])
            mock.assert_called_once_with(ssh_handler, 'web-prod-01')
            assert result is True

    def test_host_clear(self, ssh_handler):
        """Test: /ssh host <name> clear routes correctly."""
        with patch('merlya.repl.commands.ssh.hosts.clear_host_config', return_value=True) as mock:
            result = hosts.handle_host(ssh_handler, ['web-prod-01', 'clear'])
            mock.assert_called_once_with(ssh_handler, 'web-prod-01')
            assert result is True


class TestOverviewDisplay:
    """Tests for SSH overview display."""

    def test_overview_without_repl(self, capsys):
        """Test: Overview without REPL shows warning."""
        handler = SSHCommandHandler(repl=None)
        result = keys.show_overview(handler)
        assert result is True
        captured = capsys.readouterr()
        assert "not available" in captured.out

    def test_overview_with_agent_running(self, ssh_handler, mock_repl):
        """Test: Overview shows agent status when running."""
        with patch.object(mock_repl.credentials, 'supports_agent', return_value=True):
            with patch.object(mock_repl.credentials, 'get_agent_keys', return_value=['key1']):
                with patch.object(mock_repl.credentials, 'get_ssh_keys', return_value=[]):
                    result = keys.show_overview(ssh_handler)

        assert result is True


class TestAgentDisplay:
    """Tests for SSH agent display."""

    def test_agent_without_repl(self, capsys):
        """Test: Agent status without REPL shows warning."""
        handler = SSHCommandHandler(repl=None)
        result = agent.show_agent(handler)
        assert result is True
        captured = capsys.readouterr()
        assert "not available" in captured.out

    def test_agent_not_available(self, ssh_handler, mock_repl, capsys):
        """Test: Agent not available shows warning."""
        with patch.object(mock_repl.credentials, 'supports_agent', return_value=False):
            result = agent.show_agent(ssh_handler)

        assert result is True
        captured = capsys.readouterr()
        assert "not available" in captured.out


class TestKeysDisplay:
    """Tests for SSH keys display."""

    def test_keys_without_repl(self, capsys):
        """Test: Keys list without REPL shows warning."""
        handler = SSHCommandHandler(repl=None)
        result = keys.show_keys(handler)
        assert result is True
        captured = capsys.readouterr()
        assert "not available" in captured.out

    def test_keys_no_keys_found(self, ssh_handler, mock_repl, capsys):
        """Test: No keys found shows message."""
        with patch.object(mock_repl.credentials, 'get_ssh_keys', return_value=[]):
            result = keys.show_keys(ssh_handler)

        assert result is True
        captured = capsys.readouterr()
        assert "No SSH keys found" in captured.out

    def test_keys_list(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: Keys list shows available keys."""
        with patch.object(mock_repl.credentials, 'get_ssh_keys', return_value=[mock_ssh_key]):
            with patch.object(mock_repl.credentials, 'get_variable', return_value=None):
                with patch.object(mock_repl.credentials, 'get_default_key', return_value=None):
                    result = keys.show_keys(ssh_handler)

        assert result is True


class TestIntegration:
    """Integration tests for SSH command flow."""

    def test_full_flow_set_and_clear_global_key(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: Full flow of setting and clearing global key."""
        # Set key with mocked validation
        with patch(
            'merlya.repl.commands.ssh.keys.validate_ssh_key_path',
            return_value=(True, mock_ssh_key, None)
        ):
            with patch('builtins.input', return_value='n'):
                keys.set_global_key(ssh_handler, [mock_ssh_key])

        assert mock_repl.credential_manager.get_variable("ssh_key_global") == mock_ssh_key

        # Clear key
        keys.clear_global_key(ssh_handler)

        assert mock_repl.credential_manager.get_variable("ssh_key_global") is None

    def test_full_flow_host_configuration(self, ssh_handler, mock_repl, mock_ssh_key):
        """Test: Full flow of configuring host SSH."""
        ssh_handler._repo = MagicMock()
        ssh_handler._repo.get_host_by_name.return_value = {
            "hostname": "web-prod-01",
            "metadata": {}
        }

        # Set host key with mocked validation
        with patch(
            'merlya.repl.commands.ssh.hosts.validate_ssh_key_path',
            return_value=(True, mock_ssh_key, None)
        ):
            with patch('builtins.input', side_effect=[mock_ssh_key, 'y']):
                with patch('getpass.getpass', return_value='passphrase'):
                    hosts.set_host_key(ssh_handler, "web-prod-01")

        # Verify add_host was called
        ssh_handler._repo.add_host.assert_called()

        # Verify passphrase was cached
        assert mock_repl.credential_manager.get_variable("ssh-passphrase-web-prod-01") == "passphrase"
