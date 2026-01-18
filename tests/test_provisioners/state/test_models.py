"""Tests for state models."""

from __future__ import annotations

import pytest

from merlya.provisioners.state.models import (
    DriftResult,
    DriftStatus,
    ResourceState,
    ResourceStatus,
    StateSnapshot,
)


class TestResourceStatus:
    """Test ResourceStatus enum."""

    def test_status_values(self) -> None:
        """Test status enum values."""
        assert ResourceStatus.PENDING.value == "pending"
        assert ResourceStatus.CREATING.value == "creating"
        assert ResourceStatus.ACTIVE.value == "active"
        assert ResourceStatus.DELETED.value == "deleted"
        assert ResourceStatus.FAILED.value == "failed"


class TestResourceState:
    """Test ResourceState model."""

    def test_create_minimal(self) -> None:
        """Test creating resource with minimal fields."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
        )

        assert resource.resource_id == "i-12345"
        assert resource.status == ResourceStatus.UNKNOWN
        assert resource.expected_config == {}
        assert resource.actual_config == {}

    def test_create_full(self) -> None:
        """Test creating resource with all fields."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            region="us-east-1",
            status=ResourceStatus.ACTIVE,
            expected_config={"instance_type": "t3.micro"},
            actual_config={"instance_type": "t3.micro"},
            tags={"env": "prod"},
            outputs={"public_ip": "1.2.3.4"},
        )

        assert resource.region == "us-east-1"
        assert resource.status == ResourceStatus.ACTIVE
        assert resource.tags == {"env": "prod"}
        assert resource.outputs["public_ip"] == "1.2.3.4"

    def test_mark_updated(self) -> None:
        """Test mark_updated updates timestamp."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
        )
        original_time = resource.updated_at

        resource.mark_updated()

        assert resource.updated_at >= original_time

    def test_mark_checked(self) -> None:
        """Test mark_checked updates last_checked_at."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
        )
        assert resource.last_checked_at is None

        resource.mark_checked()

        assert resource.last_checked_at is not None

    def test_save_for_rollback(self) -> None:
        """Test save_for_rollback preserves current config."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            actual_config={"instance_type": "t3.micro"},
        )
        assert resource.previous_config is None

        resource.save_for_rollback()

        assert resource.previous_config == {"instance_type": "t3.micro"}

    def test_has_drift_no_config(self) -> None:
        """Test has_drift returns False with no config."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
        )

        assert resource.has_drift() is False

    def test_has_drift_matching_config(self) -> None:
        """Test has_drift returns False when configs match."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
            actual_config={"instance_type": "t3.micro"},
        )

        assert resource.has_drift() is False

    def test_has_drift_different_config(self) -> None:
        """Test has_drift returns True when configs differ."""
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
            actual_config={"instance_type": "t3.large"},
        )

        assert resource.has_drift() is True


class TestDriftResult:
    """Test DriftResult model."""

    def test_no_drift_factory(self) -> None:
        """Test no_drift factory method."""
        result = DriftResult.no_drift("i-12345")

        assert result.resource_id == "i-12345"
        assert result.status == DriftStatus.NO_DRIFT
        assert result.differences == {}

    def test_missing_factory(self) -> None:
        """Test missing factory method."""
        result = DriftResult.missing("i-12345")

        assert result.status == DriftStatus.MISSING

    def test_drifted_factory(self) -> None:
        """Test drifted factory method."""
        differences = {"instance_type": ("t3.micro", "t3.large")}
        result = DriftResult.drifted("i-12345", differences)

        assert result.status == DriftStatus.DRIFTED
        assert result.differences == differences

    def test_from_error_factory(self) -> None:
        """Test from_error factory method."""
        result = DriftResult.from_error("i-12345", "Connection failed")

        assert result.status == DriftStatus.UNKNOWN
        assert result.error == "Connection failed"


class TestStateSnapshot:
    """Test StateSnapshot model."""

    @pytest.fixture
    def sample_resource(self) -> ResourceState:
        """Create a sample resource."""
        return ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            status=ResourceStatus.ACTIVE,
        )

    def test_create_empty_snapshot(self) -> None:
        """Test creating empty snapshot."""
        snapshot = StateSnapshot(snapshot_id="snap-001")

        assert snapshot.snapshot_id == "snap-001"
        assert snapshot.resource_count == 0

    def test_add_resource(self, sample_resource: ResourceState) -> None:
        """Test adding resource to snapshot."""
        snapshot = StateSnapshot(snapshot_id="snap-001")

        snapshot.add_resource(sample_resource)

        assert snapshot.resource_count == 1
        assert "i-12345" in snapshot.resources

    def test_get_resource(self, sample_resource: ResourceState) -> None:
        """Test getting resource from snapshot."""
        snapshot = StateSnapshot(snapshot_id="snap-001")
        snapshot.add_resource(sample_resource)

        result = snapshot.get_resource("i-12345")
        assert result is not None
        assert result.name == "web-server"

        assert snapshot.get_resource("nonexistent") is None

    def test_remove_resource(self, sample_resource: ResourceState) -> None:
        """Test removing resource from snapshot."""
        snapshot = StateSnapshot(snapshot_id="snap-001")
        snapshot.add_resource(sample_resource)

        result = snapshot.remove_resource("i-12345")
        assert result is True
        assert snapshot.resource_count == 0

        result = snapshot.remove_resource("nonexistent")
        assert result is False

    def test_list_by_status(self, sample_resource: ResourceState) -> None:
        """Test listing resources by status."""
        snapshot = StateSnapshot(snapshot_id="snap-001")
        snapshot.add_resource(sample_resource)

        active = snapshot.list_by_status(ResourceStatus.ACTIVE)
        assert len(active) == 1

        pending = snapshot.list_by_status(ResourceStatus.PENDING)
        assert len(pending) == 0

    def test_list_by_provider(self, sample_resource: ResourceState) -> None:
        """Test listing resources by provider."""
        snapshot = StateSnapshot(snapshot_id="snap-001")
        snapshot.add_resource(sample_resource)

        aws_resources = snapshot.list_by_provider("aws")
        assert len(aws_resources) == 1

        gcp_resources = snapshot.list_by_provider("gcp")
        assert len(gcp_resources) == 0

    def test_list_by_type(self, sample_resource: ResourceState) -> None:
        """Test listing resources by type."""
        snapshot = StateSnapshot(snapshot_id="snap-001")
        snapshot.add_resource(sample_resource)

        instances = snapshot.list_by_type("aws_instance")
        assert len(instances) == 1

        buckets = snapshot.list_by_type("aws_s3_bucket")
        assert len(buckets) == 0
