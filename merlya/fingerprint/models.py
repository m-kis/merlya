"""
Merlya Fingerprint - Models.

Pydantic models for semantic signatures and approval tracking.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class SemanticSignature(BaseModel):
    """
    Semantic signature extracted from a command.

    Captures the intent and risk of a command in a normalized form
    that can be cached and compared across sessions.
    """

    # Classification
    action_type: str = Field(
        description="Type of action (e.g., 'http_request', 'file_write', 'service_restart')"
    )
    verb: str | None = Field(
        default=None,
        description="HTTP verb if applicable (GET, POST, DELETE, etc.)",
    )

    # Targets
    targets: list[str] = Field(
        default_factory=list,
        description="What the command affects (URLs, paths, services)",
    )

    # Risk assessment
    risk_level: Literal["low", "medium", "high", "critical"] = Field(
        default="low",
        description="Assessed risk level of the operation",
    )

    # Normalized form
    normalized_template: str = Field(
        description="Generic form with {placeholders} (e.g., 'curl -X {verb} {url}')",
    )

    # Original command for reference
    original_command: str = Field(
        description="The original command that was analyzed",
    )

    # Metadata
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def signature_hash(self) -> str:
        """
        SHA256 hash of the normalized template.

        Used for caching approval decisions across similar commands.
        """
        return hashlib.sha256(self.normalized_template.encode()).hexdigest()[:16]

    def matches_template(self, other: SemanticSignature) -> bool:
        """
        Check if this signature matches another's template.

        Args:
            other: Another signature to compare.

        Returns:
            True if templates match.
        """
        return self.signature_hash == other.signature_hash


class ApprovalRecord(BaseModel):
    """
    Record of an approval decision for a signature.

    Stores whether a command was approved, by whom, and for what scope.
    """

    signature_hash: str = Field(description="Hash of the approved signature")
    scope: Literal["once", "session", "permanent"] = Field(description="Scope of the approval")
    approved: bool = Field(description="Whether the command was approved")

    # Context
    original_command: str = Field(description="The command that was approved")
    host: str | None = Field(default=None, description="Target host if applicable")

    # Timing
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = Field(
        default=None,
        description="When this approval expires (for session scope)",
    )

    # Audit
    approved_by: str = Field(
        default="user",
        description="Who approved this (user, policy, etc.)",
    )
    reason: str | None = Field(
        default=None,
        description="Optional reason for approval/rejection",
    )

    def is_expired(self) -> bool:
        """Check if this approval has expired."""
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        if self.expires_at.tzinfo is None:
            expires_aware = self.expires_at.replace(tzinfo=UTC)
            return now > expires_aware
        return now > self.expires_at


class FingerprintResult(BaseModel):
    """
    Result of fingerprint extraction with approval status.

    Combines the semantic signature with cached approval state.
    """

    signature: SemanticSignature
    cached_approval: ApprovalRecord | None = None
    requires_new_approval: bool = True

    @property
    def is_pre_approved(self) -> bool:
        """Check if this signature has valid pre-approval."""
        if self.cached_approval is None:
            return False
        if not self.cached_approval.approved:
            return False
        return not self.cached_approval.is_expired()
