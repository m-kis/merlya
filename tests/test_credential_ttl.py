"""
Test for credential TTL functionality and singleton pattern.

Quick validation that:
- Session credentials expire after TTL
- Singleton pattern ensures credentials are shared across instances
"""
import time

from merlya.security.credentials import (
    CredentialManager,
    VariableType,
    get_credential_manager,
)


def test_credential_ttl_expiration():
    """Test: Credentials expire after TTL."""
    cm = CredentialManager()

    # Set TTL to 1 second for testing
    original_ttl = cm.CREDENTIAL_TTL
    cm.CREDENTIAL_TTL = 1

    try:
        # Cache a credential
        cm._cache_credential("test_key", "user", "pass")

        # Should be retrievable immediately
        cached = cm._get_cached_credential("test_key")
        assert cached == ("user", "pass"), "Credential should be cached"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired and return None
        cached = cm._get_cached_credential("test_key")
        assert cached is None, "Credential should have expired"

    finally:
        # Restore original TTL
        cm.CREDENTIAL_TTL = original_ttl


def test_credential_cleanup():
    """Test: Expired credentials are cleaned up."""
    cm = CredentialManager()

    # Set TTL to 1 second
    original_ttl = cm.CREDENTIAL_TTL
    cm.CREDENTIAL_TTL = 1

    try:
        # Cache multiple credentials
        cm._cache_credential("key1", "user1", "pass1")
        cm._cache_credential("key2", "user2", "pass2")
        cm._cache_credential("key3", "user3", "pass3")

        assert len(cm.session_credentials) == 3, "Should have 3 cached credentials"

        # Wait for expiration
        time.sleep(1.1)

        # Cleanup expired credentials
        cm._cleanup_expired_credentials()

        assert len(cm.session_credentials) == 0, "All credentials should be removed"

    finally:
        cm.CREDENTIAL_TTL = original_ttl


def test_has_db_credentials_respects_ttl():
    """Test: has_db_credentials returns False for expired credentials."""
    cm = CredentialManager()

    original_ttl = cm.CREDENTIAL_TTL
    cm.CREDENTIAL_TTL = 1

    try:
        # Cache a credential
        cm._cache_credential("mongodb@testhost", "user", "pass")

        # Should be available immediately
        assert cm.has_db_credentials("testhost", "mongodb"), "Credential should be available"

        # Wait for expiration
        time.sleep(1.1)

        # Should not be available after expiration
        assert not cm.has_db_credentials("testhost", "mongodb"), "Credential should have expired"

    finally:
        cm.CREDENTIAL_TTL = original_ttl


# =============================================================================
# Singleton Pattern Tests
# =============================================================================


def test_singleton_returns_same_instance():
    """Test: Multiple CredentialManager() calls return the same instance."""
    cm1 = CredentialManager()
    cm2 = CredentialManager()

    assert cm1 is cm2, "Singleton should return the same instance"


def test_get_credential_manager_returns_singleton():
    """Test: get_credential_manager() returns the singleton instance."""
    cm = CredentialManager()
    getter_cm = get_credential_manager()

    assert cm is getter_cm, "get_credential_manager should return the singleton"


def test_singleton_shares_variables_across_instances():
    """
    Test: Variables set on one 'instance' are visible to all others.

    This is the critical test that validates the fix for:
    - SSH passphrase set via /ssh passphrase command
    - Should be accessible when SSHManager creates CredentialManager()
    """
    # Simulate REPL setting a passphrase
    cm_repl = CredentialManager()
    cm_repl.set_variable("ssh-passphrase-id_ed25519", "test-passphrase", VariableType.SECRET)

    # Simulate SSHManager creating its own CredentialManager()
    # (before the fix, this would have an empty _variables dict)
    cm_ssh = CredentialManager()

    # The passphrase should be accessible
    passphrase = cm_ssh.get_variable("ssh-passphrase-id_ed25519")
    assert passphrase == "test-passphrase", (
        "Passphrase set in REPL should be accessible in SSH manager"
    )


def test_singleton_shares_host_variables():
    """Test: Host variables are shared across singleton instances."""
    cm1 = CredentialManager()
    cm1.set_host("proddb", "db-prod-001.example.com")

    cm2 = CredentialManager()
    host = cm2.get_variable("proddb")

    assert host == "db-prod-001.example.com", "Host variable should be shared"


def test_reset_instance_clears_singleton():
    """Test: reset_instance() creates a fresh singleton."""
    cm1 = CredentialManager()
    cm1.set_variable("test-key", "test-value", VariableType.CONFIG)

    # Reset the singleton
    CredentialManager.reset_instance()

    # New instance should be fresh
    cm2 = CredentialManager()
    assert cm1 is not cm2, "After reset, a new instance should be created"
    assert cm2.get_variable("test-key") is None, "Variables should be cleared after reset"


def test_singleton_with_storage_manager_updates():
    """Test: Providing storage_manager to existing singleton updates storage."""
    from unittest.mock import MagicMock

    # Create initial singleton without storage
    cm1 = CredentialManager()
    assert cm1._storage is None

    # Create mock storage manager
    mock_storage = MagicMock()
    mock_storage.get_config.return_value = {}

    # Providing storage_manager to existing singleton should update it
    cm2 = CredentialManager(storage_manager=mock_storage)
    assert cm1 is cm2, "Should be same singleton"
    assert cm1._storage is mock_storage, "Storage should be updated"


# =============================================================================
# Thread Safety Tests
# =============================================================================


def test_singleton_thread_safety():
    """Test: Concurrent instantiation creates only one instance."""
    import threading

    instances = []
    errors = []

    def create_instance():
        try:
            cm = CredentialManager()
            instances.append(cm)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=create_instance) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent instantiation: {errors}"
    assert len(instances) == 10, "All threads should get an instance"
    # All threads should get the same instance
    assert all(inst is instances[0] for inst in instances), "Singleton violated"


def test_concurrent_variable_access():
    """Test: Concurrent reads/writes don't corrupt data."""
    import threading

    cm = CredentialManager()
    errors = []
    success_count = {"writes": 0, "reads": 0}

    def writer(key_prefix: str):
        try:
            for i in range(50):
                cm.set_variable(f"{key_prefix}-{i}", f"value-{i}", VariableType.CONFIG)
                success_count["writes"] += 1
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(50):
                _ = cm.list_variables()
                success_count["reads"] += 1
        except Exception as e:
            errors.append(e)

    # Mix writers and readers
    threads = []
    for i in range(3):
        threads.append(threading.Thread(target=writer, args=(f"key{i}",)))
    for _ in range(2):
        threads.append(threading.Thread(target=reader))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent access errors: {errors}"
    assert success_count["writes"] == 150, "All writes should complete"
    assert success_count["reads"] == 100, "All reads should complete"
