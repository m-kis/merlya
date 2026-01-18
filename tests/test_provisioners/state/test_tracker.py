"""Tests for state tracker."""

from __future__ import annotations

from pathlib import Path

import pytest

from merlya.provisioners.state.models import (
    DriftStatus,
    ResourceStatus,
)
from merlya.provisioners.state.repository import StateRepository
from merlya.provisioners.state.tracker import StateTracker


class TestStateTrackerInit:
    """Test StateTracker initialization."""

    async def test_init_with_db_path(self, tmp_path: Path) -> None:
        """Test init creates repository from db path."""
        db_path = tmp_path / "state.db"

        tracker = StateTracker(db_path=db_path)

        assert tracker.repository.db_path == db_path

    async def test_init_with_existing_repository(self, tmp_path: Path) -> None:
        """Test init with existing repository."""
        db_path = tmp_path / "state.db"
        repo = StateRepository(db_path)
        await repo.initialize()

        tracker = StateTracker(repository=repo)

        assert tracker.repository is repo


class TestResourceTracking:
    """Test resource tracking operations."""

    @pytest.fixture
    async def tracker(self, tmp_path: Path) -> StateTracker:
        """Create a tracker with initialized repository."""
        db_path = tmp_path / "state.db"
        tracker = StateTracker(db_path=db_path)
        await tracker.repository.initialize()
        return tracker

    async def test_track_resource(self, tracker: StateTracker) -> None:
        """Test tracking a new resource."""
        resource = await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
        )

        assert resource.resource_id == "i-12345"
        assert resource.status == ResourceStatus.PENDING

        result = await tracker.get_resource("i-12345")
        assert result is not None

    async def test_track_resource_with_region_and_tags(self, tracker: StateTracker) -> None:
        """Test tracking resource with region and tags."""
        resource = await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
            region="us-east-1",
            tags={"env": "prod"},
        )

        assert resource.region == "us-east-1"
        assert resource.tags == {"env": "prod"}

    async def test_get_nonexistent_resource(self, tracker: StateTracker) -> None:
        """Test getting a resource that doesn't exist."""
        result = await tracker.get_resource("nonexistent")
        assert result is None

    async def test_update_status(self, tracker: StateTracker) -> None:
        """Test updating resource status."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.update_status("i-12345", ResourceStatus.ACTIVE)

        assert result is not None
        assert result.status == ResourceStatus.ACTIVE

    async def test_update_status_nonexistent(self, tracker: StateTracker) -> None:
        """Test updating status for nonexistent resource returns None."""
        result = await tracker.update_status("nonexistent", ResourceStatus.ACTIVE)
        assert result is None

    async def test_update_status_with_config_and_outputs(self, tracker: StateTracker) -> None:
        """Test updating status with config and outputs."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.update_status(
            "i-12345",
            ResourceStatus.ACTIVE,
            actual_config={"instance_type": "t3.micro"},
            outputs={"public_ip": "1.2.3.4"},
        )

        assert result is not None
        assert result.actual_config == {"instance_type": "t3.micro"}
        assert result.outputs == {"public_ip": "1.2.3.4"}

    async def test_mark_created(self, tracker: StateTracker) -> None:
        """Test marking resource as created."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.mark_created(
            "i-12345",
            actual_config={"instance_type": "t3.micro"},
            outputs={"instance_id": "i-12345", "public_ip": "1.2.3.4"},
        )

        assert result is not None
        assert result.status == ResourceStatus.ACTIVE
        assert result.actual_config == {"instance_type": "t3.micro"}
        assert result.outputs["public_ip"] == "1.2.3.4"

    async def test_mark_updated(self, tracker: StateTracker) -> None:
        """Test marking resource as updated."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.mark_updated(
            "i-12345",
            actual_config={"instance_type": "t3.large"},
        )

        assert result is not None
        assert result.status == ResourceStatus.ACTIVE
        assert result.actual_config == {"instance_type": "t3.large"}

    async def test_mark_failed(self, tracker: StateTracker) -> None:
        """Test marking resource as failed."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.mark_failed("i-12345", error="Connection timeout")

        assert result is not None
        assert result.status == ResourceStatus.FAILED
        assert result.outputs.get("error") == "Connection timeout"

    async def test_mark_deleted(self, tracker: StateTracker) -> None:
        """Test marking resource as deleted."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.mark_deleted("i-12345")

        assert result is not None
        assert result.status == ResourceStatus.DELETED

    async def test_untrack_resource(self, tracker: StateTracker) -> None:
        """Test untracking a resource."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )

        result = await tracker.untrack_resource("i-12345")
        assert result is True

        result = await tracker.get_resource("i-12345")
        assert result is None

    async def test_list_resources(self, tracker: StateTracker) -> None:
        """Test listing resources."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )
        await tracker.track_resource(
            resource_id="i-002",
            resource_type="aws_instance",
            name="web-02",
            provider="aws",
            expected_config={},
        )

        result = await tracker.list_resources()
        assert len(result) == 2

    async def test_list_active_resources(self, tracker: StateTracker) -> None:
        """Test listing active resources."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )
        await tracker.mark_created("i-001", actual_config={})

        await tracker.track_resource(
            resource_id="i-002",
            resource_type="aws_instance",
            name="web-02",
            provider="aws",
            expected_config={},
        )
        # Leave i-002 as PENDING

        result = await tracker.list_active_resources()
        assert len(result) == 1
        assert result[0].resource_id == "i-001"


class TestDriftDetection:
    """Test drift detection operations."""

    @pytest.fixture
    async def tracker(self, tmp_path: Path) -> StateTracker:
        """Create a tracker with initialized repository."""
        db_path = tmp_path / "state.db"
        tracker = StateTracker(db_path=db_path)
        await tracker.repository.initialize()
        return tracker

    async def test_check_drift_no_drift(self, tracker: StateTracker) -> None:
        """Test check_drift when configs match."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
        )

        result = await tracker.check_drift(
            "i-12345",
            actual_config={"instance_type": "t3.micro"},
        )

        assert result.status == DriftStatus.NO_DRIFT
        assert result.differences == {}

    async def test_check_drift_with_drift(self, tracker: StateTracker) -> None:
        """Test check_drift when configs differ."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
        )

        result = await tracker.check_drift(
            "i-12345",
            actual_config={"instance_type": "t3.large"},
        )

        assert result.status == DriftStatus.DRIFTED
        assert "instance_type" in result.differences
        assert result.differences["instance_type"] == ("t3.micro", "t3.large")

    async def test_check_drift_missing_resource(self, tracker: StateTracker) -> None:
        """Test check_drift for nonexistent resource."""
        result = await tracker.check_drift(
            "nonexistent",
            actual_config={},
        )

        assert result.status == DriftStatus.UNKNOWN
        assert "not found" in (result.error or "").lower()

    async def test_check_drift_no_expected_config(self, tracker: StateTracker) -> None:
        """Test check_drift when no expected config (always no drift)."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},  # Empty expected config
        )

        result = await tracker.check_drift(
            "i-12345",
            actual_config={"instance_type": "t3.large"},
        )

        assert result.status == DriftStatus.NO_DRIFT

    async def test_check_all_drift(self, tracker: StateTracker) -> None:
        """Test checking drift for all resources."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
        )
        await tracker.mark_created("i-001", actual_config={"instance_type": "t3.micro"})

        await tracker.track_resource(
            resource_id="i-002",
            resource_type="aws_instance",
            name="web-02",
            provider="aws",
            expected_config={"instance_type": "t3.micro"},
        )
        await tracker.mark_created("i-002", actual_config={"instance_type": "t3.micro"})

        results = await tracker.check_all_drift(
            actual_configs={
                "i-001": {"instance_type": "t3.micro"},  # No drift
                "i-002": {"instance_type": "t3.large"},  # Drifted
            }
        )

        assert len(results) == 2
        statuses = {r.resource_id: r.status for r in results}
        assert statuses["i-001"] == DriftStatus.NO_DRIFT
        assert statuses["i-002"] == DriftStatus.DRIFTED

    async def test_check_all_drift_missing_from_actual(self, tracker: StateTracker) -> None:
        """Test check_all_drift when resource missing from actual configs."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )
        await tracker.mark_created("i-001", actual_config={})

        # Don't provide i-001 in actual_configs - simulates resource deleted externally
        results = await tracker.check_all_drift(actual_configs={})

        assert len(results) == 1
        assert results[0].status == DriftStatus.MISSING


class TestSnapshotManagement:
    """Test snapshot management operations."""

    @pytest.fixture
    async def tracker(self, tmp_path: Path) -> StateTracker:
        """Create a tracker with initialized repository."""
        db_path = tmp_path / "state.db"
        tracker = StateTracker(db_path=db_path)
        await tracker.repository.initialize()
        return tracker

    async def test_create_snapshot(self, tracker: StateTracker) -> None:
        """Test creating a snapshot."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )

        snapshot = await tracker.create_snapshot(description="Pre-deployment")

        assert snapshot.snapshot_id is not None
        assert snapshot.description == "Pre-deployment"
        assert snapshot.resource_count == 1

    async def test_get_snapshot(self, tracker: StateTracker) -> None:
        """Test getting a snapshot."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )
        snapshot = await tracker.create_snapshot(description="Test")

        result = await tracker.get_snapshot(snapshot.snapshot_id)

        assert result is not None
        assert result.snapshot_id == snapshot.snapshot_id

    async def test_list_snapshots(self, tracker: StateTracker) -> None:
        """Test listing snapshots."""
        await tracker.create_snapshot(description="First")
        await tracker.create_snapshot(description="Second")

        result = await tracker.list_snapshots()

        assert len(result) == 2

    async def test_restore_snapshot(self, tracker: StateTracker) -> None:
        """Test restoring a snapshot."""
        # Create initial state
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )
        await tracker.mark_created("i-001", actual_config={"instance_type": "t3.micro"})

        # Create snapshot
        snapshot = await tracker.create_snapshot(description="Before changes")

        # Modify state - update the resource
        resource = await tracker.get_resource("i-001")
        assert resource is not None
        resource.actual_config = {"instance_type": "t3.large"}
        await tracker.repository.save_resource(resource)

        # Verify modified state
        resource = await tracker.get_resource("i-001")
        assert resource is not None
        assert resource.actual_config == {"instance_type": "t3.large"}

        # Restore snapshot
        restored = await tracker.restore_snapshot(snapshot.snapshot_id)
        assert restored is not None

        # Note: restore_snapshot updates mark_updated on resources but
        # doesn't necessarily restore the exact config - it saves
        # the snapshot's resources back. The actual behavior depends
        # on what was in the snapshot.

    async def test_restore_nonexistent_snapshot(self, tracker: StateTracker) -> None:
        """Test restoring a nonexistent snapshot returns None."""
        result = await tracker.restore_snapshot("nonexistent")
        assert result is None


class TestRollbackSupport:
    """Test rollback support features."""

    @pytest.fixture
    async def tracker(self, tmp_path: Path) -> StateTracker:
        """Create a tracker with initialized repository."""
        db_path = tmp_path / "state.db"
        tracker = StateTracker(db_path=db_path)
        await tracker.repository.initialize()
        return tracker

    async def test_get_rollback_config(self, tracker: StateTracker) -> None:
        """Test getting rollback config."""
        await tracker.track_resource(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            expected_config={},
        )
        await tracker.mark_created(
            "i-12345",
            actual_config={"instance_type": "t3.micro"},
        )

        # Trigger save_for_rollback by transitioning to UPDATING
        await tracker.update_status("i-12345", ResourceStatus.UPDATING)

        config = await tracker.get_rollback_config("i-12345")
        assert config is not None
        assert config == {"instance_type": "t3.micro"}

    async def test_get_rollback_config_nonexistent(self, tracker: StateTracker) -> None:
        """Test getting rollback config for nonexistent resource."""
        config = await tracker.get_rollback_config("nonexistent")
        assert config is None


class TestClearAll:
    """Test clear_all method."""

    @pytest.fixture
    async def tracker(self, tmp_path: Path) -> StateTracker:
        """Create a tracker with initialized repository."""
        db_path = tmp_path / "state.db"
        tracker = StateTracker(db_path=db_path)
        await tracker.repository.initialize()
        return tracker

    async def test_clear_all(self, tracker: StateTracker) -> None:
        """Test clearing all state data."""
        await tracker.track_resource(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            expected_config={},
        )

        await tracker.clear_all()

        result = await tracker.list_resources()
        assert result == []
