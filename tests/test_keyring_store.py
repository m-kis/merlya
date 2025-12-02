"""
Tests for keyring secret storage.

Tests the KeyringSecretStore class and its integration with CredentialManager.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from merlya.security.keyring_store import (
    KEY_PATTERN,
    MAX_KEY_LENGTH,
    KeyringSecretStore,
    get_keyring_store,
    reset_keyring_store,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton instance before each test."""
    reset_keyring_store()
    yield
    reset_keyring_store()


@pytest.fixture
def mock_keyring():
    """Mock keyring module for testing without actual keyring access."""
    with patch("merlya.security.keyring_store.keyring") as mock:
        with patch("merlya.security.keyring_store.HAS_KEYRING", True):
            # Mock successful keyring backend detection
            mock.get_keyring.return_value = MagicMock(__class__=type("MockKeyring", (), {}))
            yield mock


class TestKeyringSecretStore:
    """Tests for KeyringSecretStore class."""

    def test_init_without_keyring(self):
        """Test initialization when keyring is not available."""
        with patch("merlya.security.keyring_store.HAS_KEYRING", False):
            store = KeyringSecretStore()
            assert not store.is_available
            assert store.backend_name is None

    def test_init_with_keyring(self, mock_keyring):
        """Test initialization with keyring available."""
        store = KeyringSecretStore()
        assert store.is_available
        assert store.backend_name is not None

    def test_store_secret(self, mock_keyring):
        """Test storing a secret."""
        mock_keyring.get_password.return_value = None  # No existing metadata

        store = KeyringSecretStore()
        result = store.store("test-key", "test-value")

        assert result is True
        mock_keyring.set_password.assert_called()
        # Verify the key was stored with service prefix
        calls = mock_keyring.set_password.call_args_list
        assert any("merlya/test-key" in str(call) for call in calls)

    def test_store_secret_without_keyring(self):
        """Test storing fails gracefully when keyring unavailable."""
        with patch("merlya.security.keyring_store.HAS_KEYRING", False):
            store = KeyringSecretStore()
            result = store.store("test-key", "test-value")
            assert result is False

    def test_retrieve_secret(self, mock_keyring):
        """Test retrieving a secret."""
        mock_keyring.get_password.return_value = "secret-value"

        store = KeyringSecretStore()
        result = store.retrieve("test-key")

        assert result == "secret-value"
        mock_keyring.get_password.assert_called_with(
            "merlya", "merlya/test-key"
        )

    def test_retrieve_missing_secret(self, mock_keyring):
        """Test retrieving non-existent secret returns None."""
        mock_keyring.get_password.return_value = None

        store = KeyringSecretStore()
        result = store.retrieve("missing-key")

        assert result is None

    def test_delete_secret(self, mock_keyring):
        """Test deleting a secret."""
        mock_keyring.get_password.return_value = "key1\nkey2"  # Metadata with keys

        store = KeyringSecretStore()
        result = store.delete("key1")

        assert result is True
        mock_keyring.delete_password.assert_called()

    def test_delete_missing_secret(self, mock_keyring):
        """Test deleting non-existent secret."""
        from merlya.security.keyring_store import PasswordDeleteError

        mock_keyring.delete_password.side_effect = PasswordDeleteError()
        mock_keyring.get_password.return_value = None

        store = KeyringSecretStore()
        result = store.delete("missing-key")

        assert result is False

    def test_list_keys(self, mock_keyring):
        """Test listing secret keys."""
        mock_keyring.get_password.return_value = "key1\nkey2\nkey3"

        store = KeyringSecretStore()
        keys = store.list_keys()

        assert keys == ["key1", "key2", "key3"]

    def test_list_keys_empty(self, mock_keyring):
        """Test listing when no keys exist."""
        mock_keyring.get_password.return_value = None

        store = KeyringSecretStore()
        keys = store.list_keys()

        assert keys == []

    def test_has_secret(self, mock_keyring):
        """Test checking if secret exists."""
        mock_keyring.get_password.return_value = "test-key\nother-key"

        store = KeyringSecretStore()
        assert store.has_secret("test-key") is True
        assert store.has_secret("missing-key") is False

    def test_clear_all(self, mock_keyring):
        """Test clearing all secrets."""
        mock_keyring.get_password.return_value = "key1\nkey2"

        store = KeyringSecretStore()
        deleted = store.clear_all()

        assert deleted == 2
        assert mock_keyring.delete_password.call_count >= 2


class TestKeyValidation:
    """Tests for secret key validation."""

    def test_empty_key_rejected(self, mock_keyring):
        """Test that empty keys are rejected."""
        store = KeyringSecretStore()
        with pytest.raises(ValueError, match="cannot be empty"):
            store.store("", "value")

    def test_key_too_long_rejected(self, mock_keyring):
        """Test that keys exceeding max length are rejected."""
        store = KeyringSecretStore()
        long_key = "a" * (MAX_KEY_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            store.store(long_key, "value")

    def test_key_with_newline_rejected(self, mock_keyring):
        """Test that keys with newlines are rejected."""
        store = KeyringSecretStore()
        with pytest.raises(ValueError, match="cannot contain newlines"):
            store.store("key\nwith\nnewlines", "value")

    def test_key_with_carriage_return_rejected(self, mock_keyring):
        """Test that keys with carriage returns are rejected."""
        store = KeyringSecretStore()
        with pytest.raises(ValueError, match="cannot contain newlines"):
            store.store("key\rwith\rcr", "value")

    def test_key_with_invalid_chars_rejected(self, mock_keyring):
        """Test that keys with invalid characters are rejected."""
        store = KeyringSecretStore()
        invalid_keys = ["key with spaces", "key@symbol", "key#hash", "key$dollar"]
        for key in invalid_keys:
            with pytest.raises(ValueError, match="can only contain"):
                store.store(key, "value")

    def test_valid_key_patterns(self, mock_keyring):
        """Test that valid key patterns are accepted."""
        mock_keyring.get_password.return_value = None  # No existing metadata
        store = KeyringSecretStore()

        valid_keys = [
            "simple-key",
            "key_with_underscores",
            "key123",
            "cred/mongodb/host/user",
            "UPPERCASE_KEY",
            "MixedCase-Key_123",
        ]
        for key in valid_keys:
            # Should not raise
            result = store.store(key, "value")
            assert result is True

    def test_key_pattern_regex(self):
        """Test the KEY_PATTERN regex directly."""
        # Valid patterns
        assert KEY_PATTERN.match("simple")
        assert KEY_PATTERN.match("with-dash")
        assert KEY_PATTERN.match("with_underscore")
        assert KEY_PATTERN.match("with/slash/path")
        assert KEY_PATTERN.match("Mixed123")
        assert KEY_PATTERN.match("with.dot")  # dots allowed for filenames like privatekey.pem
        assert KEY_PATTERN.match("ssh-passphrase-id_ed25519.pem")

        # Invalid patterns
        assert not KEY_PATTERN.match("")
        assert not KEY_PATTERN.match("with space")
        assert not KEY_PATTERN.match("with@at")
        assert not KEY_PATTERN.match("with:colon")

    def test_validation_on_retrieve(self, mock_keyring):
        """Test that validation is applied on retrieve."""
        store = KeyringSecretStore()
        with pytest.raises(ValueError, match="cannot be empty"):
            store.retrieve("")

    def test_validation_on_delete(self, mock_keyring):
        """Test that validation is applied on delete."""
        store = KeyringSecretStore()
        with pytest.raises(ValueError, match="cannot be empty"):
            store.delete("")


class TestKeyringCredentialHelpers:
    """Tests for credential storage helpers."""

    def test_store_credential(self, mock_keyring):
        """Test storing service credentials."""
        mock_keyring.get_password.return_value = None

        store = KeyringSecretStore()
        result = store.store_credential("mongodb", "db-prod-01", "admin", "secret123")

        assert result is True
        # Should store both user and pass
        calls = mock_keyring.set_password.call_args_list
        assert any("cred/mongodb/db-prod-01/user" in str(call) for call in calls)
        assert any("cred/mongodb/db-prod-01/pass" in str(call) for call in calls)

    def test_retrieve_credential(self, mock_keyring):
        """Test retrieving service credentials."""
        def get_password_mock(service, key):
            if "user" in key:
                return "admin"
            elif "pass" in key:
                return "secret123"
            return None

        mock_keyring.get_password.side_effect = get_password_mock

        store = KeyringSecretStore()
        cred = store.retrieve_credential("mongodb", "db-prod-01")

        assert cred is not None
        assert cred["username"] == "admin"
        assert cred["password"] == "secret123"

    def test_retrieve_missing_credential(self, mock_keyring):
        """Test retrieving non-existent credentials."""
        mock_keyring.get_password.return_value = None

        store = KeyringSecretStore()
        cred = store.retrieve_credential("mongodb", "missing-host")

        assert cred is None

    def test_delete_credential(self, mock_keyring):
        """Test deleting service credentials."""
        mock_keyring.get_password.return_value = "cred/mongodb/db-prod-01/user\ncred/mongodb/db-prod-01/pass"

        store = KeyringSecretStore()
        result = store.delete_credential("mongodb", "db-prod-01")

        assert result is True

    def test_list_credentials(self, mock_keyring):
        """Test listing stored credentials."""
        mock_keyring.get_password.return_value = (
            "cred/mongodb/db-prod-01/user\n"
            "cred/mongodb/db-prod-01/pass\n"
            "cred/mysql/db-prod-02/user\n"
            "cred/mysql/db-prod-02/pass\n"
            "api-key"  # Regular secret, not a credential
        )

        store = KeyringSecretStore()
        creds = store.list_credentials()

        assert len(creds) == 2
        assert {"service": "mongodb", "host": "db-prod-01"} in creds
        assert {"service": "mysql", "host": "db-prod-02"} in creds


class TestKeyringStoreSingleton:
    """Tests for singleton pattern."""

    def test_singleton_returns_same_instance(self, mock_keyring):
        """Test that get_keyring_store returns same instance."""
        store1 = get_keyring_store()
        store2 = get_keyring_store()

        assert store1 is store2

    def test_reset_clears_singleton(self, mock_keyring):
        """Test that reset clears the singleton."""
        store1 = get_keyring_store()
        reset_keyring_store()
        store2 = get_keyring_store()

        assert store1 is not store2


class TestCredentialManagerKeyringIntegration:
    """Tests for CredentialManager keyring integration."""

    def test_get_variable_checks_keyring(self, mock_keyring):
        """Test that get_variable checks keyring for unknown keys."""
        mock_keyring.get_password.return_value = "keyring-secret"

        from merlya.security.credentials import CredentialManager

        cm = CredentialManager()
        # Force keyring store to use our mock
        cm._keyring_store = KeyringSecretStore()

        result = cm.get_variable("unknown-secret")

        assert result == "keyring-secret"

    def test_get_variable_checks_env_fallback(self, mock_keyring):
        """Test that get_variable falls back to environment."""
        mock_keyring.get_password.return_value = None

        from merlya.security.credentials import CredentialManager

        with patch.dict(os.environ, {"MERLYA_MY_SECRET": "env-value"}):
            cm = CredentialManager()
            cm._keyring_store = KeyringSecretStore()

            result = cm.get_variable("my-secret")

            assert result == "env-value"

    def test_get_variable_session_takes_priority(self, mock_keyring):
        """Test that session variables take priority over keyring."""
        mock_keyring.get_password.return_value = "keyring-value"

        from merlya.security.credentials import CredentialManager, VariableType

        cm = CredentialManager()
        cm._keyring_store = KeyringSecretStore()
        cm.set_variable("test-key", "session-value", VariableType.SECRET)

        result = cm.get_variable("test-key")

        assert result == "session-value"

    def test_keyring_value_cached_in_session(self, mock_keyring):
        """Test that keyring values are cached in session."""
        mock_keyring.get_password.return_value = "keyring-secret"

        from merlya.security.credentials import CredentialManager, VariableType

        cm = CredentialManager()
        cm._keyring_store = KeyringSecretStore()

        # First access loads from keyring
        result1 = cm.get_variable("cached-key")
        assert result1 == "keyring-secret"

        # Should now be in session cache
        assert "cached-key" in cm._variables
        assert cm._variables["cached-key"][1] == VariableType.SECRET
