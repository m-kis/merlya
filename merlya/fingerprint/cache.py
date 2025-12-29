"""
Merlya Fingerprint - Cache.

Caches approval decisions for semantic signatures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal, cast

from loguru import logger

from merlya.fingerprint.models import ApprovalRecord, SemanticSignature


class ApprovalScope(str, Enum):
    """Scope for approval decisions."""

    ONCE = "once"  # This execution only
    SESSION = "session"  # Until end of session
    PERMANENT = "permanent"  # Store permanently (careful!)
    REFUSED = "refused"  # Explicitly refused


class FingerprintCache:
    """
    Cache for fingerprint approval decisions.

    Provides in-memory caching with optional persistence.
    Handles approval scopes and expiration.
    """

    def __init__(self, session_ttl_hours: int = 8):
        """
        Initialize fingerprint cache.

        Args:
            session_ttl_hours: TTL for session-scoped approvals.
        """
        self._cache: dict[str, ApprovalRecord] = {}
        self._session_ttl = timedelta(hours=session_ttl_hours)

    def get(self, signature: SemanticSignature) -> ApprovalRecord | None:
        """
        Get cached approval for a signature.

        Args:
            signature: The signature to look up.

        Returns:
            ApprovalRecord if found and valid, None otherwise.
        """
        record = self._cache.get(signature.signature_hash)

        if record is None:
            return None

        if record.is_expired():
            logger.debug(f"🕐 Approval expired for {signature.signature_hash}")
            del self._cache[signature.signature_hash]
            return None

        return record

    def set(
        self,
        signature: SemanticSignature,
        approved: bool,
        scope: ApprovalScope,
        host: str | None = None,
        reason: str | None = None,
    ) -> ApprovalRecord:
        """
        Cache an approval decision.

        Args:
            signature: The signature to cache.
            approved: Whether it was approved.
            scope: Scope of the approval.
            host: Target host if applicable.
            reason: Optional reason for the decision.

        Returns:
            The created ApprovalRecord.
        """
        expires_at = None
        if scope == ApprovalScope.SESSION:
            expires_at = datetime.now(UTC) + self._session_ttl
        elif scope == ApprovalScope.ONCE:
            # Expires immediately after this check
            expires_at = datetime.now(UTC)

        record = ApprovalRecord(
            signature_hash=signature.signature_hash,
            scope=cast("Literal['once', 'session', 'permanent']", scope.value),
            approved=approved,
            original_command=signature.original_command,
            host=host,
            approved_at=datetime.now(UTC),
            expires_at=expires_at,
            reason=reason,
        )

        # Don't cache "once" scope
        if scope != ApprovalScope.ONCE:
            self._cache[signature.signature_hash] = record
            logger.debug(
                f"📋 Cached approval: {signature.signature_hash} "
                f"(scope={scope.value}, approved={approved})"
            )

        return record

    def revoke(self, signature: SemanticSignature) -> bool:
        """
        Revoke a cached approval.

        Args:
            signature: The signature to revoke.

        Returns:
            True if approval was revoked, False if not found.
        """
        if signature.signature_hash in self._cache:
            del self._cache[signature.signature_hash]
            logger.debug(f"🚫 Revoked approval for {signature.signature_hash}")
            return True
        return False

    def clear(self) -> int:
        """
        Clear all cached approvals.

        Returns:
            Number of approvals cleared.
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"🗑️ Cleared {count} cached approvals")
        return count

    def cleanup_expired(self) -> int:
        """
        Remove expired approvals from cache.

        Returns:
            Number of expired approvals removed.
        """
        expired = [sig_hash for sig_hash, record in self._cache.items() if record.is_expired()]

        for sig_hash in expired:
            del self._cache[sig_hash]

        if expired:
            logger.debug(f"🧹 Cleaned up {len(expired)} expired approvals")

        return len(expired)

    def stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats.
        """
        self.cleanup_expired()

        approved_count = sum(1 for r in self._cache.values() if r.approved)
        refused_count = len(self._cache) - approved_count

        scope_counts: dict[str, int] = {}
        for record in self._cache.values():
            scope_counts[record.scope] = scope_counts.get(record.scope, 0) + 1

        return {
            "total": len(self._cache),
            "approved": approved_count,
            "refused": refused_count,
            "by_scope": scope_counts,
        }

    def __len__(self) -> int:
        """Get number of cached approvals."""
        return len(self._cache)

    def __contains__(self, signature: SemanticSignature) -> bool:
        """Check if signature has cached approval."""
        return self.get(signature) is not None
