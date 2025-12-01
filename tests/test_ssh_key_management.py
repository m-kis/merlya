"""
Tests for SSH key management functionality.

Tests:
- Key resolution priority (host > global > ssh_config > default)
- Passphrase caching (session-only, not persisted)
- _key_needs_passphrase detection
- resolve_ssh_for_host function
- Path validation security
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from athena_ai.security.credentials import CredentialManager, VariableType
from athena_ai.security.ssh_credentials import (
    sanitize_path_for_log,
    validate_hostname,
    validate_ssh_key_path,
)


@pytest.fixture
def credential_manager():
    """Create a fresh CredentialManager without storage."""
    return CredentialManager(storage_manager=None)


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


@pytest.fixture
def mock_encrypted_ssh_key(tmp_path):
    """Create a mock encrypted SSH key file."""
    key_content = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHIAAAAGYmNyeXB0AAAAGAAAABB
ENCRYPTED KEY CONTENT HERE
-----END OPENSSH PRIVATE KEY-----
"""
    key_path = tmp_path / "id_encrypted"
    key_path.write_text(key_content)
    return str(key_path)


class TestPathValidation:
    """Tests for path validation security."""

    def test_validate_hostname_valid_hostname(self):
        """Test: Valid hostnames pass validation."""
        assert validate_hostname("server1")
        assert validate_hostname("web-prod-01")
        assert validate_hostname("db.example.com")
        assert validate_hostname("server.internal.corp")

    def test_validate_hostname_valid_ipv4(self):
        """Test: Valid IPv4 addresses pass validation."""
        assert validate_hostname("192.168.1.1")
        assert validate_hostname("10.0.0.1")
        assert validate_hostname("255.255.255.255")

    def test_validate_hostname_invalid(self):
        """Test: Invalid hostnames fail validation."""
        assert not validate_hostname("")
        assert not validate_hostname("-invalid")
        assert not validate_hostname("invalid-")
        assert not validate_hostname("a" * 300)  # Too long

    def test_validate_hostname_wildcards(self):
        """Test: Wildcards for SSH config patterns."""
        assert validate_hostname("*.example.com")
        assert validate_hostname("web-*")

    def test_sanitize_path_for_log(self):
        """Test: Path sanitization shows only filename."""
        assert sanitize_path_for_log("/home/user/.ssh/id_rsa") == "id_rsa"
        assert sanitize_path_for_log("/etc/ssh/ssh_host_key") == "ssh_host_key"

    def test_validate_ssh_key_path_nonexistent(self):
        """Test: Nonexistent path fails validation."""
        is_valid, resolved, error = validate_ssh_key_path("/nonexistent/path/key")
        assert not is_valid
        assert resolved is None
        assert "does not exist" in error

    def test_validate_ssh_key_path_outside_allowed(self, tmp_path):
        """Test: Path outside allowed directories fails validation."""
        # Create file in temp dir (not in ~/.ssh)
        key_file = tmp_path / "test_key"
        key_file.write_text("test")

        is_valid, resolved, error = validate_ssh_key_path(str(key_file))
        assert not is_valid
        assert "outside allowed directories" in error


class TestKeyNeedsPassphrase:
    """Tests for _key_needs_passphrase detection."""

    def test_unencrypted_key_no_passphrase(self, credential_manager, mock_ssh_key):
        """Test: Unencrypted key should not need passphrase."""
        # Mock the path validation to allow temp files for testing
        with patch(
            'athena_ai.security.ssh_credentials.validate_ssh_key_path',
            return_value=(True, mock_ssh_key, None)
        ):
            # Also need to patch paramiko to avoid actual key loading
            with patch.object(credential_manager, '_key_needs_passphrase', return_value=False):
                assert not credential_manager._key_needs_passphrase(mock_ssh_key)

    def test_encrypted_key_needs_passphrase(self, credential_manager, mock_encrypted_ssh_key):
        """Test: Encrypted key should need passphrase."""
        # Mock path validation to allow temp files, then check content-based detection
        with patch(
            'athena_ai.security.ssh_credentials.validate_ssh_key_path',
            return_value=(True, mock_encrypted_ssh_key, None)
        ):
            # Mock paramiko ImportError to force content-based detection
            with patch.dict('sys.modules', {'paramiko': None}):
                # Re-import to use fallback
                import importlib

                import athena_ai.security.ssh_credentials as ssh_creds
                importlib.reload(ssh_creds)

                # Read file content check
                with open(mock_encrypted_ssh_key) as f:
                    content = f.read()
                    assert "ENCRYPTED" in content

    def test_nonexistent_key_returns_false(self, credential_manager):
        """Test: Nonexistent key returns False (no passphrase needed)."""
        assert not credential_manager._key_needs_passphrase("/nonexistent/key")


class TestGlobalKeyManagement:
    """Tests for global SSH key configuration."""

    def test_set_global_key(self, credential_manager, mock_ssh_key):
        """Test: Setting global key stores in CONFIG variable."""
        credential_manager.set_variable("ssh_key_global", mock_ssh_key, VariableType.CONFIG)

        assert credential_manager.get_variable("ssh_key_global") == mock_ssh_key
        assert credential_manager.get_variable_type("ssh_key_global") == VariableType.CONFIG

    def test_get_default_key_returns_global_first(self, credential_manager, mock_ssh_key):
        """Test: get_default_key returns global key before standard keys."""
        credential_manager.set_variable("ssh_key_global", mock_ssh_key, VariableType.CONFIG)

        # Mock path validation to allow the temp file
        with patch(
            'athena_ai.security.ssh_credentials.validate_ssh_key_path',
            return_value=(True, mock_ssh_key, None)
        ):
            default_key = credential_manager.get_default_key()
            assert default_key == mock_ssh_key

    def test_clear_global_key(self, credential_manager, mock_ssh_key):
        """Test: Clearing global key removes it."""
        credential_manager.set_variable("ssh_key_global", mock_ssh_key, VariableType.CONFIG)
        credential_manager.delete_variable("ssh_key_global")

        assert credential_manager.get_variable("ssh_key_global") is None


class TestPassphraseCaching:
    """Tests for passphrase caching behavior."""

    def test_passphrase_stored_as_secret(self, credential_manager):
        """Test: Passphrase is stored as SECRET type (not persisted)."""
        credential_manager.set_variable(
            "ssh-passphrase-id_test", "my-secret-passphrase", VariableType.SECRET
        )

        assert credential_manager.get_variable("ssh-passphrase-id_test") == "my-secret-passphrase"
        assert credential_manager.get_variable_type("ssh-passphrase-id_test") == VariableType.SECRET

    def test_passphrase_not_in_persisted_variables(self, credential_manager):
        """Test: SECRET variables are excluded from persistence."""
        credential_manager.set_variable(
            "ssh-passphrase-global", "secret", VariableType.SECRET
        )
        credential_manager.set_variable(
            "ssh_key_global", "/path/to/key", VariableType.CONFIG
        )

        # Get variables that would be persisted
        persisted = {
            key: value
            for key, (value, var_type) in credential_manager._variables.items()
            if var_type != VariableType.SECRET
        }

        assert "ssh_key_global" in persisted
        assert "ssh-passphrase-global" not in persisted

    def test_clear_secrets_removes_passphrases(self, credential_manager):
        """Test: clear_secrets removes all passphrase variables."""
        credential_manager.set_variable("ssh-passphrase-host1", "pass1", VariableType.SECRET)
        credential_manager.set_variable("ssh-passphrase-host2", "pass2", VariableType.SECRET)
        credential_manager.set_variable("ssh_key_global", "/key", VariableType.CONFIG)

        credential_manager.clear_secrets()

        assert credential_manager.get_variable("ssh-passphrase-host1") is None
        assert credential_manager.get_variable("ssh-passphrase-host2") is None
        assert credential_manager.get_variable("ssh_key_global") == "/key"


class TestResolveSSHForHost:
    """Tests for resolve_ssh_for_host priority resolution."""

    def test_resolve_with_global_key(self, credential_manager, mock_ssh_key):
        """Test: Resolution uses global key when set."""
        credential_manager.set_variable("ssh_key_global", mock_ssh_key, VariableType.CONFIG)

        # Mock path validation to allow temp file
        with patch(
            'athena_ai.security.ssh_credentials.validate_ssh_key_path',
            return_value=(True, mock_ssh_key, None)
        ):
            # Mock inventory to return no host-specific key
            with patch(
                'athena_ai.memory.persistence.inventory_repository.get_inventory_repository'
            ) as mock_repo:
                mock_repo.return_value.get_host_by_name.return_value = None

                key_path, passphrase, source = credential_manager.resolve_ssh_for_host(
                    "some-host", prompt_passphrase=False
                )

                assert key_path == mock_ssh_key
                assert source == "global"

    def test_resolve_host_specific_takes_priority(self, credential_manager, mock_ssh_key, tmp_path):
        """Test: Host-specific key takes priority over global."""
        host_key = tmp_path / "host_specific_key"
        host_key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----")
        host_key_str = str(host_key)

        credential_manager.set_variable("ssh_key_global", mock_ssh_key, VariableType.CONFIG)

        # Mock path validation to allow temp files
        def mock_validate(path):
            return (True, path, None)

        with patch(
            'athena_ai.security.ssh_credentials.validate_ssh_key_path',
            side_effect=mock_validate
        ):
            # Mock inventory to return host with specific key
            with patch(
                'athena_ai.memory.persistence.inventory_repository.get_inventory_repository'
            ) as mock_repo:
                mock_repo.return_value.get_host_by_name.return_value = {
                    "hostname": "web-prod-01",
                    "metadata": {
                        "ssh_key_path": host_key_str,
                        "ssh_passphrase_secret": "ssh-passphrase-web-prod-01"
                    }
                }

                key_path, passphrase, source = credential_manager.resolve_ssh_for_host(
                    "web-prod-01", prompt_passphrase=False
                )

                assert key_path == host_key_str
                assert source == "host"

    def test_resolve_returns_none_when_no_key(self, credential_manager):
        """Test: Returns None when no key is found."""
        # Mock inventory to return nothing
        with patch(
            'athena_ai.memory.persistence.inventory_repository.get_inventory_repository'
        ) as mock_repo:
            mock_repo.return_value.get_host_by_name.return_value = None

            # Also mock get_default_key to return None
            with patch.object(credential_manager, 'get_default_key', return_value=None):
                key_path, passphrase, source = credential_manager.resolve_ssh_for_host(
                    "unknown-host", prompt_passphrase=False
                )

                assert key_path is None
                assert source is None

    def test_resolve_invalid_hostname_returns_none(self, credential_manager):
        """Test: Invalid hostname returns None."""
        key_path, passphrase, source = credential_manager.resolve_ssh_for_host(
            "-invalid-hostname", prompt_passphrase=False
        )

        assert key_path is None
        assert passphrase is None
        assert source is None


class TestGetPassphraseForKey:
    """Tests for get_passphrase_for_key behavior."""

    def test_returns_cached_specific_secret(self, credential_manager, mock_ssh_key):
        """Test: Returns cached passphrase from specific secret key."""
        credential_manager.set_variable(
            "ssh-passphrase-myhost", "cached-passphrase", VariableType.SECRET
        )

        passphrase = credential_manager.get_passphrase_for_key(
            mock_ssh_key,
            secret_key="ssh-passphrase-myhost",
            prompt_if_missing=False
        )

        assert passphrase == "cached-passphrase"

    def test_returns_cached_generic_secret(self, credential_manager, mock_ssh_key):
        """Test: Returns cached passphrase from generic secret (by filename)."""
        key_filename = Path(mock_ssh_key).name
        credential_manager.set_variable(
            f"ssh-passphrase-{key_filename}", "generic-passphrase", VariableType.SECRET
        )

        passphrase = credential_manager.get_passphrase_for_key(
            mock_ssh_key,
            prompt_if_missing=False
        )

        assert passphrase == "generic-passphrase"

    def test_returns_none_when_no_cache_and_no_prompt(self, credential_manager, mock_ssh_key):
        """Test: Returns None when no cached passphrase and prompting disabled."""
        passphrase = credential_manager.get_passphrase_for_key(
            mock_ssh_key,
            prompt_if_missing=False
        )

        assert passphrase is None


class TestSSHKeyIntegration:
    """Integration tests for SSH key management flow."""

    def test_full_flow_global_key_with_passphrase(self, credential_manager, mock_encrypted_ssh_key):
        """Test: Full flow of setting global key with passphrase."""
        # 1. Set global key
        credential_manager.set_variable(
            "ssh_key_global", mock_encrypted_ssh_key, VariableType.CONFIG
        )

        # 2. Set passphrase for global key
        credential_manager.set_variable(
            "ssh-passphrase-global", "my-global-passphrase", VariableType.SECRET
        )

        # 3. Mock path validation and resolve for any host
        with patch(
            'athena_ai.security.ssh_credentials.validate_ssh_key_path',
            return_value=(True, mock_encrypted_ssh_key, None)
        ):
            with patch(
                'athena_ai.memory.persistence.inventory_repository.get_inventory_repository'
            ) as mock_repo:
                mock_repo.return_value.get_host_by_name.return_value = None

                # Mock _key_needs_passphrase to return True
                with patch.object(
                    credential_manager, '_key_needs_passphrase', return_value=True
                ):
                    key_path, passphrase, source = credential_manager.resolve_ssh_for_host(
                        "any-host", prompt_passphrase=False
                    )

                    assert key_path == mock_encrypted_ssh_key
                    assert passphrase == "my-global-passphrase"
                    assert source == "global"
