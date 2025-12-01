"""
Test for credential TTL functionality.

Quick validation that session credentials expire after TTL.
"""
import time

from merlya.security.credentials import CredentialManager


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
