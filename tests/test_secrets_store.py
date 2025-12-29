"""
Tests for merlya/secrets/store.py - SecretStore.

Covers keyring integration, memory fallback, persistence, and convenience functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from merlya.secrets.store import (
    SecretStore,
    get_secret,
    get_secret_store,
    has_secret,
    list_secrets,
    remove_secret,
    set_secret,
)


class TestSecretStoreInit:
    """Test SecretStore initialization."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    def test_init_without_keyring(self, tmp_path):
        """Test initialization when keyring is not available."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "keyring not installed")

                store = SecretStore()

                assert store._keyring_available is False
                assert store._memory_store == {}
                # Empty because we use temp file
                assert store._secret_names == set()

    def test_init_with_keyring(self, tmp_path):
        """Test initialization when keyring is available."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (True, None)

                store = SecretStore()

                assert store._keyring_available is True


class TestSecretStoreCheckKeyring:
    """Test _check_keyring method."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    def test_check_keyring_runs(self, tmp_path):
        """Test _check_keyring runs and returns tuple."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            store = object.__new__(SecretStore)
            store._keyring_available = False
            store._memory_store = {}
            store._secret_names = set()

            # Just test that it returns a tuple
            result = store._check_keyring()

            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], bool)


class TestSecretStoreSecretNames:
    """Test secret names persistence."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    def test_load_secret_names_no_file(self, tmp_path):
        """Test _load_secret_names when file doesn't exist."""
        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", tmp_path / "nonexistent.json"):
            store = object.__new__(SecretStore)
            store._secret_names = set()

            store._load_secret_names()

            assert store._secret_names == set()

    def test_load_secret_names_valid_file(self, tmp_path):
        """Test _load_secret_names with valid file (legacy format, migrated on save)."""
        index_file = tmp_path / "secrets.json"
        # Legacy format (plain list) - still supported for migration
        index_file.write_text(json.dumps(["secret1", "secret2"]))
        # Set permissions to 600 (owner read/write only)
        index_file.chmod(0o600)

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            store = object.__new__(SecretStore)
            store._secret_names = set()

            store._load_secret_names()

            assert store._secret_names == {"secret1", "secret2"}

    def test_load_secret_names_invalid_json(self, tmp_path):
        """Test _load_secret_names with invalid JSON."""
        index_file = tmp_path / "secrets.json"
        index_file.write_text("not valid json {")

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            store = object.__new__(SecretStore)
            store._secret_names = set()

            # Should not raise
            store._load_secret_names()

            assert store._secret_names == set()

    def test_save_secret_names(self, tmp_path):
        """Test _save_secret_names writes to file with HMAC."""
        index_file = tmp_path / "subdir" / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            store = object.__new__(SecretStore)
            store._secret_names = {"alpha", "beta", "gamma"}

            store._save_secret_names()

            assert index_file.exists()
            data = json.loads(index_file.read_text())
            # New format: {"names": [...], "hmac": "..."}
            assert "names" in data
            assert "hmac" in data
            assert data["names"] == ["alpha", "beta", "gamma"]  # Sorted
            # HMAC should be a hex string
            assert len(data["hmac"]) == 64  # SHA256 hex = 64 chars

    def test_save_secret_names_error(self, tmp_path):
        """Test _save_secret_names handles errors gracefully."""
        # Use a read-only directory
        index_file = Path("/nonexistent/directory/secrets.json")

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            store = object.__new__(SecretStore)
            store._secret_names = {"secret"}

            # Should not raise
            store._save_secret_names()


class TestSecretStoreOperations:
    """Test SecretStore CRUD operations."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    @pytest.fixture
    def memory_store(self, tmp_path):
        """Create store with memory backend."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "test mode")
                store = SecretStore()
                yield store

    def test_set_memory_store(self, memory_store):
        """Test set with memory backend."""
        memory_store.set("test_key", "test_value")

        assert "test_key" in memory_store._memory_store
        assert memory_store._memory_store["test_key"] == "test_value"
        assert "test_key" in memory_store._secret_names

    def test_get_memory_store(self, memory_store):
        """Test get with memory backend."""
        memory_store._memory_store["my_secret"] = "my_value"

        result = memory_store.get("my_secret")

        assert result == "my_value"

    def test_get_not_found(self, memory_store):
        """Test get returns None for non-existent secret."""
        result = memory_store.get("nonexistent")

        assert result is None

    def test_remove_memory_store(self, memory_store):
        """Test remove with memory backend."""
        memory_store._memory_store["to_delete"] = "value"
        memory_store._secret_names.add("to_delete")

        result = memory_store.remove("to_delete")

        assert result is True
        assert "to_delete" not in memory_store._memory_store
        assert "to_delete" not in memory_store._secret_names

    def test_remove_not_found(self, memory_store):
        """Test remove returns True even for non-existent (no error)."""
        result = memory_store.remove("nonexistent")

        # Should return True (no exception)
        assert result is True

    def test_has_true(self, memory_store):
        """Test has returns True for existing secret."""
        memory_store._memory_store["exists"] = "value"

        assert memory_store.has("exists") is True

    def test_has_false(self, memory_store):
        """Test has returns False for non-existent secret."""
        assert memory_store.has("nonexistent") is False

    def test_is_secure_false(self, memory_store):
        """Test is_secure returns False for memory store."""
        assert memory_store.is_secure is False

    def test_list_names(self, memory_store):
        """Test list_names returns sorted names."""
        memory_store._secret_names = {"zebra", "alpha", "beta"}

        result = memory_store.list_names()

        assert result == ["alpha", "beta", "zebra"]

    def test_list_keys_alias(self, memory_store):
        """Test list_keys is alias for list_names."""
        memory_store._secret_names = {"key1", "key2"}

        assert memory_store.list_keys() == memory_store.list_names()

    def test_delete_alias(self, memory_store):
        """Test delete is alias for remove."""
        memory_store._memory_store["to_delete"] = "value"
        memory_store._secret_names.add("to_delete")

        result = memory_store.delete("to_delete")

        assert result is True
        assert "to_delete" not in memory_store._memory_store


class TestSecretStoreWithKeyring:
    """Test SecretStore with keyring backend (integration tests)."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    def test_keyring_available_property(self, tmp_path):
        """Test _keyring_available flag is set correctly."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            # Test with keyring flag set manually
            store = object.__new__(SecretStore)
            store._keyring_available = True
            store._memory_store = {}
            store._secret_names = set()

            assert store.is_secure is True

            store._keyring_available = False
            assert store.is_secure is False

    def test_set_updates_secret_names(self, tmp_path):
        """Test set updates secret names even with keyring."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "test")
                store = SecretStore()

                store.set("new_secret", "value")

                assert "new_secret" in store._secret_names

    def test_remove_updates_secret_names(self, tmp_path):
        """Test remove updates secret names."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "test")
                store = SecretStore()
                store.set("to_remove", "value")

                store.remove("to_remove")

                assert "to_remove" not in store._secret_names


class TestSecretStoreSingleton:
    """Test SecretStore singleton pattern."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    def test_get_instance_creates_singleton(self, tmp_path):
        """Test get_instance creates singleton."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "test")

                store1 = SecretStore.get_instance()
                store2 = SecretStore.get_instance()

                assert store1 is store2

    def test_reset_instance(self, tmp_path):
        """Test reset_instance clears singleton."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "test")

                store1 = SecretStore.get_instance()
                SecretStore.reset_instance()
                store2 = SecretStore.get_instance()

                assert store1 is not store2


class TestConvenienceFunctions:
    """Test convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before and after each test."""
        SecretStore.reset_instance()
        yield
        SecretStore.reset_instance()

    @pytest.fixture
    def mock_store(self, tmp_path):
        """Create mock store."""
        index_file = tmp_path / "secrets.json"

        with patch("merlya.secrets.store.SECRETS_INDEX_FILE", index_file):
            with patch("merlya.secrets.store.SecretStore._check_keyring") as mock_check:
                mock_check.return_value = (False, "test")
                yield

    def test_get_secret_store(self, mock_store):
        """Test get_secret_store returns singleton."""
        store = get_secret_store()
        assert isinstance(store, SecretStore)

    def test_set_secret(self, mock_store):
        """Test set_secret convenience function."""
        set_secret("my_key", "my_value")

        store = get_secret_store()
        assert store.get("my_key") == "my_value"

    def test_get_secret(self, mock_store):
        """Test get_secret convenience function."""
        store = get_secret_store()
        store._memory_store["test_key"] = "test_value"

        result = get_secret("test_key")

        assert result == "test_value"

    def test_remove_secret(self, mock_store):
        """Test remove_secret convenience function."""
        store = get_secret_store()
        store._memory_store["to_delete"] = "value"
        store._secret_names.add("to_delete")

        result = remove_secret("to_delete")

        assert result is True
        assert "to_delete" not in store._memory_store

    def test_has_secret(self, mock_store):
        """Test has_secret convenience function."""
        store = get_secret_store()
        store._memory_store["exists"] = "value"

        assert has_secret("exists") is True
        assert has_secret("nonexistent") is False

    def test_list_secrets(self, mock_store):
        """Test list_secrets convenience function."""
        store = get_secret_store()
        store._secret_names = {"secret1", "secret2"}

        result = list_secrets()

        assert result == ["secret1", "secret2"]
