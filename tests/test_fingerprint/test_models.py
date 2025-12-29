"""Tests for fingerprint models."""

from datetime import UTC, datetime, timedelta

from merlya.fingerprint.models import (
    ApprovalRecord,
    FingerprintResult,
    SemanticSignature,
)


class TestSemanticSignature:
    """Tests for SemanticSignature model."""

    def test_create_http_signature(self) -> None:
        """Test creating an HTTP request signature."""
        sig = SemanticSignature(
            action_type="http_request",
            verb="POST",
            targets=["api.example.com"],
            risk_level="medium",
            normalized_template="curl -X {post} {url}",
            original_command="curl -X POST https://api.example.com/users",
        )
        assert sig.action_type == "http_request"
        assert sig.verb == "POST"
        assert "api.example.com" in sig.targets
        assert sig.risk_level == "medium"

    def test_create_service_signature(self) -> None:
        """Test creating a service management signature."""
        sig = SemanticSignature(
            action_type="service_management",
            verb="restart",
            targets=["nginx"],
            risk_level="medium",
            normalized_template="systemctl {restart} {service}",
            original_command="systemctl restart nginx",
        )
        assert sig.action_type == "service_management"
        assert sig.verb == "restart"
        assert "nginx" in sig.targets

    def test_signature_hash_computed(self) -> None:
        """Test signature hash is computed from template."""
        sig = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="echo {message}",
            original_command="echo hello",
        )
        assert sig.signature_hash is not None
        assert len(sig.signature_hash) == 16  # First 16 chars of SHA256

    def test_same_template_same_hash(self) -> None:
        """Test same template produces same hash."""
        sig1 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="curl -X {get} {url}",
            original_command="curl https://example.com",
        )
        sig2 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=["different"],
            risk_level="high",  # Different risk
            normalized_template="curl -X {get} {url}",  # Same template
            original_command="curl https://other.com",  # Different original
        )
        assert sig1.signature_hash == sig2.signature_hash

    def test_different_template_different_hash(self) -> None:
        """Test different templates produce different hashes."""
        sig1 = SemanticSignature(
            action_type="test",
            verb="GET",
            targets=[],
            risk_level="low",
            normalized_template="curl -X {get} {url}",
            original_command="curl example.com",
        )
        sig2 = SemanticSignature(
            action_type="test",
            verb="POST",
            targets=[],
            risk_level="low",
            normalized_template="curl -X {post} {url} -d {data}",
            original_command="curl -X POST example.com -d test",
        )
        assert sig1.signature_hash != sig2.signature_hash

    def test_matches_template(self) -> None:
        """Test template matching."""
        sig1 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="systemctl {action} {service}",
            original_command="systemctl restart nginx",
        )
        sig2 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="systemctl {action} {service}",
            original_command="systemctl restart apache",
        )
        sig3 = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="service {service} {action}",
            original_command="service nginx restart",
        )
        assert sig1.matches_template(sig2)
        assert not sig1.matches_template(sig3)

    def test_timestamp_auto_set(self) -> None:
        """Test extracted_at timestamp is auto-set."""
        before = datetime.now(UTC)
        sig = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test",
            original_command="test",
        )
        after = datetime.now(UTC)
        assert before <= sig.extracted_at <= after


class TestApprovalRecord:
    """Tests for ApprovalRecord model."""

    def test_create_approval(self) -> None:
        """Test creating an approval record."""
        record = ApprovalRecord(
            signature_hash="abc123def456",
            scope="session",
            approved=True,
            original_command="curl https://example.com",
            host="web-01",
        )
        assert record.signature_hash == "abc123def456"
        assert record.scope == "session"
        assert record.approved is True
        assert record.host == "web-01"

    def test_approval_timestamp_auto_set(self) -> None:
        """Test approved_at timestamp is auto-set."""
        before = datetime.now(UTC)
        record = ApprovalRecord(
            signature_hash="test",
            scope="once",
            approved=True,
            original_command="test",
        )
        after = datetime.now(UTC)
        assert before <= record.approved_at <= after

    def test_is_expired_no_expiry(self) -> None:
        """Test non-expiring approval is never expired."""
        record = ApprovalRecord(
            signature_hash="test",
            scope="permanent",
            approved=True,
            original_command="test",
            expires_at=None,
        )
        assert record.is_expired() is False

    def test_is_expired_future_expiry(self) -> None:
        """Test future expiry is not expired."""
        record = ApprovalRecord(
            signature_hash="test",
            scope="session",
            approved=True,
            original_command="test",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert record.is_expired() is False

    def test_is_expired_past_expiry(self) -> None:
        """Test past expiry is expired."""
        record = ApprovalRecord(
            signature_hash="test",
            scope="session",
            approved=True,
            original_command="test",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert record.is_expired() is True

    def test_is_expired_handles_naive_datetime(self) -> None:
        """Test is_expired handles naive datetime."""
        past_naive = datetime.now() - timedelta(hours=1)
        record = ApprovalRecord(
            signature_hash="test",
            scope="session",
            approved=True,
            original_command="test",
            expires_at=past_naive,
        )
        assert record.is_expired() is True


class TestFingerprintResult:
    """Tests for FingerprintResult model."""

    def test_create_result_no_cache(self) -> None:
        """Test creating result without cached approval."""
        sig = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test",
            original_command="test",
        )
        result = FingerprintResult(
            signature=sig,
            cached_approval=None,
            requires_new_approval=True,
        )
        assert result.signature == sig
        assert result.cached_approval is None
        assert result.requires_new_approval is True
        assert result.is_pre_approved is False

    def test_is_pre_approved_with_valid_approval(self) -> None:
        """Test is_pre_approved with valid cached approval."""
        sig = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test",
            original_command="test",
        )
        approval = ApprovalRecord(
            signature_hash=sig.signature_hash,
            scope="session",
            approved=True,
            original_command="test",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        result = FingerprintResult(
            signature=sig,
            cached_approval=approval,
            requires_new_approval=False,
        )
        assert result.is_pre_approved is True

    def test_is_pre_approved_with_expired_approval(self) -> None:
        """Test is_pre_approved with expired cached approval."""
        sig = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test",
            original_command="test",
        )
        approval = ApprovalRecord(
            signature_hash=sig.signature_hash,
            scope="session",
            approved=True,
            original_command="test",
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # Expired
        )
        result = FingerprintResult(
            signature=sig,
            cached_approval=approval,
            requires_new_approval=True,
        )
        assert result.is_pre_approved is False

    def test_is_pre_approved_with_refused_approval(self) -> None:
        """Test is_pre_approved with refused cached approval."""
        sig = SemanticSignature(
            action_type="test",
            verb="test",
            targets=[],
            risk_level="low",
            normalized_template="test",
            original_command="test",
        )
        approval = ApprovalRecord(
            signature_hash=sig.signature_hash,
            scope="session",
            approved=False,  # Refused
            original_command="test",
        )
        result = FingerprintResult(
            signature=sig,
            cached_approval=approval,
            requires_new_approval=True,
        )
        assert result.is_pre_approved is False
