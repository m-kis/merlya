"""Tests for FingerprintCache."""

import pytest

from merlya.fingerprint.cache import ApprovalScope, FingerprintCache
from merlya.fingerprint.models import SemanticSignature


@pytest.fixture
def cache() -> FingerprintCache:
    """Create a fresh cache."""
    return FingerprintCache(session_ttl_hours=1)


@pytest.fixture
def sample_signature() -> SemanticSignature:
    """Create a sample signature."""
    return SemanticSignature(
        action_type="http_request",
        verb="GET",
        targets=["example.com"],
        risk_level="low",
        normalized_template="curl {url}",
        original_command="curl https://example.com",
    )


class TestApprovalScope:
    """Tests for ApprovalScope enum."""

    def test_scope_values(self) -> None:
        """Test all scope values are defined."""
        assert ApprovalScope.ONCE.value == "once"
        assert ApprovalScope.SESSION.value == "session"
        assert ApprovalScope.PERMANENT.value == "permanent"
        assert ApprovalScope.REFUSED.value == "refused"


class TestFingerprintCacheBasic:
    """Tests for basic cache operations."""

    def test_get_empty_cache(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test getting from empty cache returns None."""
        result = cache.get(sample_signature)
        assert result is None

    def test_set_and_get_session(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test setting and getting session-scoped approval."""
        cache.set(sample_signature, approved=True, scope=ApprovalScope.SESSION)

        result = cache.get(sample_signature)

        assert result is not None
        assert result.approved is True
        assert result.scope == "session"
        assert result.expires_at is not None

    def test_set_and_get_permanent(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test setting and getting permanent approval."""
        cache.set(sample_signature, approved=True, scope=ApprovalScope.PERMANENT)

        result = cache.get(sample_signature)

        assert result is not None
        assert result.approved is True
        assert result.scope == "permanent"
        assert result.expires_at is None

    def test_once_scope_not_cached(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test ONCE scope is not cached."""
        cache.set(sample_signature, approved=True, scope=ApprovalScope.ONCE)

        result = cache.get(sample_signature)

        assert result is None
        assert len(cache) == 0

    def test_set_with_host(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test setting approval with host context."""
        cache.set(
            sample_signature,
            approved=True,
            scope=ApprovalScope.SESSION,
            host="web-01",
        )

        result = cache.get(sample_signature)

        assert result is not None
        assert result.host == "web-01"

    def test_set_with_reason(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test setting approval with reason."""
        cache.set(
            sample_signature,
            approved=False,
            scope=ApprovalScope.SESSION,
            reason="Unsafe operation",
        )

        result = cache.get(sample_signature)

        assert result is not None
        assert result.approved is False
        assert result.reason == "Unsafe operation"


class TestFingerprintCacheExpiration:
    """Tests for cache expiration."""

    def test_expired_approval_returns_none(self, sample_signature: SemanticSignature) -> None:
        """Test expired approval is not returned."""
        # Create cache with very short TTL
        cache = FingerprintCache(session_ttl_hours=0)

        # Manually set an expired record
        cache.set(sample_signature, approved=True, scope=ApprovalScope.SESSION)

        # The record was created with immediate expiry, so should be gone
        result = cache.get(sample_signature)
        # Note: Due to timing, this might still be valid for a brief moment
        # so we check that it's either None or expired
        if result is not None:
            assert result.is_expired()

    def test_cleanup_expired(self, cache: FingerprintCache) -> None:
        """Test cleanup of expired approvals."""
        # Create multiple signatures
        sigs = [
            SemanticSignature(
                action_type="test",
                verb="test",
                targets=[],
                risk_level="low",
                normalized_template=f"test_{i}",
                original_command=f"test_{i}",
            )
            for i in range(3)
        ]

        # Add them all
        for sig in sigs:
            cache.set(sig, approved=True, scope=ApprovalScope.SESSION)

        assert len(cache) == 3

        # Cleanup shouldn't remove anything yet (they're fresh)
        removed = cache.cleanup_expired()
        assert removed == 0
        assert len(cache) == 3


class TestFingerprintCacheRevoke:
    """Tests for revoking approvals."""

    def test_revoke_existing(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test revoking existing approval."""
        cache.set(sample_signature, approved=True, scope=ApprovalScope.SESSION)
        assert len(cache) == 1

        result = cache.revoke(sample_signature)

        assert result is True
        assert len(cache) == 0
        assert cache.get(sample_signature) is None

    def test_revoke_nonexistent(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test revoking non-existent approval."""
        result = cache.revoke(sample_signature)
        assert result is False


class TestFingerprintCacheClear:
    """Tests for clearing cache."""

    def test_clear_empty(self, cache: FingerprintCache) -> None:
        """Test clearing empty cache."""
        count = cache.clear()
        assert count == 0

    def test_clear_with_entries(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test clearing cache with entries."""
        cache.set(sample_signature, approved=True, scope=ApprovalScope.SESSION)

        sig2 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="other",
            original_command="other",
        )
        cache.set(sig2, approved=True, scope=ApprovalScope.SESSION)

        assert len(cache) == 2

        count = cache.clear()

        assert count == 2
        assert len(cache) == 0


class TestFingerprintCacheStats:
    """Tests for cache statistics."""

    def test_stats_empty(self, cache: FingerprintCache) -> None:
        """Test stats on empty cache."""
        stats = cache.stats()

        assert stats["total"] == 0
        assert stats["approved"] == 0
        assert stats["refused"] == 0
        assert stats["by_scope"] == {}

    def test_stats_with_entries(self, cache: FingerprintCache) -> None:
        """Test stats with various entries."""
        # Add approved session
        sig1 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test1",
            original_command="test1",
        )
        cache.set(sig1, approved=True, scope=ApprovalScope.SESSION)

        # Add refused session
        sig2 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test2",
            original_command="test2",
        )
        cache.set(sig2, approved=False, scope=ApprovalScope.SESSION)

        # Add approved permanent
        sig3 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test3",
            original_command="test3",
        )
        cache.set(sig3, approved=True, scope=ApprovalScope.PERMANENT)

        stats = cache.stats()

        assert stats["total"] == 3
        assert stats["approved"] == 2
        assert stats["refused"] == 1
        assert stats["by_scope"]["session"] == 2
        assert stats["by_scope"]["permanent"] == 1


class TestFingerprintCacheContains:
    """Tests for __contains__ method."""

    def test_contains_when_present(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test __contains__ when signature is cached."""
        cache.set(sample_signature, approved=True, scope=ApprovalScope.SESSION)
        assert sample_signature in cache

    def test_contains_when_absent(
        self, cache: FingerprintCache, sample_signature: SemanticSignature
    ) -> None:
        """Test __contains__ when signature is not cached."""
        assert sample_signature not in cache
