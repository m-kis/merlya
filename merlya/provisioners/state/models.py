"""
Merlya Provisioners State - Models.

Data models for resource state tracking.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ResourceStatus(str, Enum):
    """Status of a managed resource."""

    PENDING = "pending"  # Resource planned but not yet created
    CREATING = "creating"  # Resource creation in progress
    ACTIVE = "active"  # Resource exists and is healthy
    UPDATING = "updating"  # Resource update in progress
    DELETING = "deleting"  # Resource deletion in progress
    DELETED = "deleted"  # Resource has been deleted
    FAILED = "failed"  # Resource operation failed
    UNKNOWN = "unknown"  # Resource state cannot be determined


class DriftStatus(str, Enum):
    """Drift detection status."""

    NO_DRIFT = "no_drift"  # Resource matches expected state
    DRIFTED = "drifted"  # Resource differs from expected state
    MISSING = "missing"  # Resource no longer exists
    UNKNOWN = "unknown"  # Unable to determine drift status


class ResourceState(BaseModel):
    """
    State of a single managed resource.

    Tracks the expected and actual state of a resource across
    provisioner operations.
    """

    # Identity
    resource_id: str = Field(description="Unique identifier for this resource")
    resource_type: str = Field(description="Type of resource (e.g., 'aws_instance')")
    name: str = Field(description="Human-readable resource name")

    # Provider context
    provider: str = Field(description="Cloud provider (aws, gcp, azure, etc.)")
    region: str | None = Field(default=None, description="Region/zone if applicable")

    # State
    status: ResourceStatus = Field(default=ResourceStatus.UNKNOWN)
    expected_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected configuration from template",
    )
    actual_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Actual configuration from provider",
    )

    # Metadata
    tags: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource outputs (IPs, ARNs, etc.)",
    )

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_checked_at: datetime | None = Field(default=None)

    # Rollback data
    previous_config: dict[str, Any] | None = Field(
        default=None,
        description="Previous configuration for rollback",
    )

    def mark_updated(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(UTC)

    def mark_checked(self) -> None:
        """Update the last_checked_at timestamp."""
        self.last_checked_at = datetime.now(UTC)

    def save_for_rollback(self) -> None:
        """Save current actual_config for potential rollback (deep copy)."""
        self.previous_config = copy.deepcopy(self.actual_config)

    def has_drift(self) -> bool:
        """Check if resource has drifted from expected state."""
        if not self.expected_config or not self.actual_config:
            return False
        return self.expected_config != self.actual_config


class DriftResult(BaseModel):
    """Result of drift detection for a resource."""

    resource_id: str
    status: DriftStatus
    differences: dict[str, tuple[Any, Any]] = Field(
        default_factory=dict,
        description="Mapping of field -> (expected, actual)",
    )
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = Field(default=None, description="Error message if detection failed")

    @classmethod
    def no_drift(cls, resource_id: str) -> DriftResult:
        """Create a no-drift result."""
        return cls(resource_id=resource_id, status=DriftStatus.NO_DRIFT)

    @classmethod
    def missing(cls, resource_id: str) -> DriftResult:
        """Create a missing resource result."""
        return cls(resource_id=resource_id, status=DriftStatus.MISSING)

    @classmethod
    def drifted(cls, resource_id: str, differences: dict[str, tuple[Any, Any]]) -> DriftResult:
        """Create a drifted result with differences."""
        return cls(
            resource_id=resource_id,
            status=DriftStatus.DRIFTED,
            differences=differences,
        )

    @classmethod
    def from_error(cls, resource_id: str, error_msg: str) -> DriftResult:
        """Create an error result."""
        return cls(
            resource_id=resource_id,
            status=DriftStatus.UNKNOWN,
            error=error_msg,
        )


class StateSnapshot(BaseModel):
    """
    Snapshot of all managed resource states.

    Represents the complete state at a point in time.
    """

    # Identity
    snapshot_id: str = Field(description="Unique snapshot identifier")

    # Context
    provider: str | None = Field(default=None, description="Provider filter")
    session_id: str | None = Field(default=None, description="Session that created this")

    # Resources
    resources: dict[str, ResourceState] = Field(
        default_factory=dict,
        description="Mapping of resource_id -> ResourceState",
    )

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    description: str | None = Field(default=None)

    @property
    def resource_count(self) -> int:
        """Get the number of resources in this snapshot."""
        return len(self.resources)

    def get_resource(self, resource_id: str) -> ResourceState | None:
        """Get a resource by ID."""
        return self.resources.get(resource_id)

    def add_resource(self, resource: ResourceState) -> None:
        """Add or update a resource in the snapshot."""
        self.resources[resource.resource_id] = resource

    def remove_resource(self, resource_id: str) -> bool:
        """Remove a resource from the snapshot."""
        if resource_id in self.resources:
            del self.resources[resource_id]
            return True
        return False

    def list_by_status(self, status: ResourceStatus) -> list[ResourceState]:
        """List resources with a specific status."""
        return [r for r in self.resources.values() if r.status == status]

    def list_by_provider(self, provider: str) -> list[ResourceState]:
        """List resources for a specific provider."""
        return [r for r in self.resources.values() if r.provider == provider]

    def list_by_type(self, resource_type: str) -> list[ResourceState]:
        """List resources of a specific type."""
        return [r for r in self.resources.values() if r.resource_type == resource_type]
