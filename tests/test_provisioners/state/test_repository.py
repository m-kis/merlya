"""Tests for state repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from merlya.provisioners.state.models import (
    ResourceState,
    ResourceStatus,
    StateSnapshot,
)
from merlya.provisioners.state.repository import MissingResourcesError, StateRepository


class TestStateRepositoryInit:
    """Test StateRepository initialization."""

    async def test_initialize_creates_tables(self, tmp_path: Path) -> None:
        """Test initialize creates required tables."""
        db_path = tmp_path / "state.db"
        repo = StateRepository(db_path)

        await repo.initialize()

        # Verify database file exists
        assert db_path.exists()

    async def test_initialize_idempotent(self, tmp_path: Path) -> None:
        """Test initialize can be called multiple times."""
        db_path = tmp_path / "state.db"
        repo = StateRepository(db_path)

        await repo.initialize()
        await repo.initialize()  # Should not raise

    async def test_default_db_path(self) -> None:
        """Test default db path when none provided."""
        repo = StateRepository()
        expected_path = Path.home() / ".merlya" / "provisioner_state.db"
        assert repo.db_path == expected_path


class TestResourceOperations:
    """Test resource CRUD operations."""

    @pytest.fixture
    async def repo(self, tmp_path: Path) -> StateRepository:
        """Create and initialize a repository."""
        db_path = tmp_path / "state.db"
        repo = StateRepository(db_path)
        await repo.initialize()
        return repo

    @pytest.fixture
    def sample_resource(self) -> ResourceState:
        """Create a sample resource."""
        return ResourceState(
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

    async def test_save_and_get_resource(
        self, repo: StateRepository, sample_resource: ResourceState
    ) -> None:
        """Test saving and retrieving a resource."""
        await repo.save_resource(sample_resource)

        result = await repo.get_resource("i-12345")

        assert result is not None
        assert result.resource_id == "i-12345"
        assert result.name == "web-server"
        assert result.provider == "aws"
        assert result.status == ResourceStatus.ACTIVE
        assert result.tags == {"env": "prod"}

    async def test_get_nonexistent_resource(self, repo: StateRepository) -> None:
        """Test getting a resource that doesn't exist."""
        result = await repo.get_resource("nonexistent")
        assert result is None

    async def test_update_resource(
        self, repo: StateRepository, sample_resource: ResourceState
    ) -> None:
        """Test updating a resource."""
        await repo.save_resource(sample_resource)

        sample_resource.status = ResourceStatus.DELETED
        sample_resource.actual_config = {"instance_type": "t3.large"}
        await repo.save_resource(sample_resource)

        result = await repo.get_resource("i-12345")
        assert result is not None
        assert result.status == ResourceStatus.DELETED
        assert result.actual_config == {"instance_type": "t3.large"}

    async def test_delete_resource(
        self, repo: StateRepository, sample_resource: ResourceState
    ) -> None:
        """Test deleting a resource."""
        await repo.save_resource(sample_resource)

        result = await repo.delete_resource("i-12345")
        assert result is True

        result = await repo.get_resource("i-12345")
        assert result is None

    async def test_delete_nonexistent_resource(self, repo: StateRepository) -> None:
        """Test deleting a resource that doesn't exist."""
        result = await repo.delete_resource("nonexistent")
        assert result is False

    async def test_list_resources_empty(self, repo: StateRepository) -> None:
        """Test listing resources when empty."""
        result = await repo.list_resources()
        assert result == []

    async def test_list_resources(self, repo: StateRepository) -> None:
        """Test listing all resources."""
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
        )
        r2 = ResourceState(
            resource_id="i-002",
            resource_type="aws_instance",
            name="web-02",
            provider="aws",
        )

        await repo.save_resource(r1)
        await repo.save_resource(r2)

        result = await repo.list_resources()
        assert len(result) == 2

    async def test_list_resources_by_provider(self, repo: StateRepository) -> None:
        """Test listing resources filtered by provider."""
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
        )
        r2 = ResourceState(
            resource_id="g-001",
            resource_type="compute_instance",
            name="web-02",
            provider="gcp",
        )

        await repo.save_resource(r1)
        await repo.save_resource(r2)

        result = await repo.list_resources(provider="aws")
        assert len(result) == 1
        assert result[0].provider == "aws"

    async def test_list_resources_by_status(self, repo: StateRepository) -> None:
        """Test listing resources filtered by status."""
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            status=ResourceStatus.ACTIVE,
        )
        r2 = ResourceState(
            resource_id="i-002",
            resource_type="aws_instance",
            name="web-02",
            provider="aws",
            status=ResourceStatus.DELETED,
        )

        await repo.save_resource(r1)
        await repo.save_resource(r2)

        result = await repo.list_resources(status=ResourceStatus.ACTIVE)
        assert len(result) == 1
        assert result[0].status == ResourceStatus.ACTIVE

    async def test_list_resources_by_type(self, repo: StateRepository) -> None:
        """Test listing resources filtered by type."""
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
        )
        r2 = ResourceState(
            resource_id="b-001",
            resource_type="aws_s3_bucket",
            name="bucket-01",
            provider="aws",
        )

        await repo.save_resource(r1)
        await repo.save_resource(r2)

        result = await repo.list_resources(resource_type="aws_instance")
        assert len(result) == 1
        assert result[0].resource_type == "aws_instance"


class TestSnapshotOperations:
    """Test snapshot operations."""

    @pytest.fixture
    async def repo(self, tmp_path: Path) -> StateRepository:
        """Create and initialize a repository."""
        db_path = tmp_path / "state.db"
        repo = StateRepository(db_path)
        await repo.initialize()
        return repo

    @pytest.fixture
    def sample_snapshot(self) -> StateSnapshot:
        """Create a sample snapshot with resources."""
        snapshot = StateSnapshot(snapshot_id="snap-001", description="Test snapshot")
        snapshot.add_resource(
            ResourceState(
                resource_id="i-12345",
                resource_type="aws_instance",
                name="web-server",
                provider="aws",
                status=ResourceStatus.ACTIVE,
            )
        )
        return snapshot

    async def test_save_and_get_snapshot(
        self, repo: StateRepository, sample_snapshot: StateSnapshot
    ) -> None:
        """Test saving and retrieving a snapshot."""
        # First save the resources (snapshots only store references)
        for resource in sample_snapshot.resources.values():
            await repo.save_resource(resource)

        await repo.save_snapshot(sample_snapshot)

        result = await repo.get_snapshot("snap-001")

        assert result is not None
        assert result.snapshot_id == "snap-001"
        assert result.description == "Test snapshot"
        assert result.resource_count == 1
        assert "i-12345" in result.resources

    async def test_get_nonexistent_snapshot(self, repo: StateRepository) -> None:
        """Test getting a snapshot that doesn't exist."""
        result = await repo.get_snapshot("nonexistent")
        assert result is None

    async def test_get_snapshot_missing_resources_raises(self, repo: StateRepository) -> None:
        """Test missing snapshot resources are surfaced as an error."""
        snapshot = StateSnapshot(snapshot_id="snap-001", description="Test snapshot")
        snapshot.add_resource(
            ResourceState(
                resource_id="i-missing",
                resource_type="aws_instance",
                name="web-server",
                provider="aws",
                status=ResourceStatus.ACTIVE,
            )
        )
        await repo.save_snapshot(snapshot)

        with pytest.raises(MissingResourcesError) as excinfo:
            await repo.get_snapshot("snap-001")

        assert excinfo.value.snapshot_id == "snap-001"
        assert excinfo.value.missing_resource_ids == ["i-missing"]

    async def test_get_snapshot_partial_missing_resources_raises(
        self, repo: StateRepository
    ) -> None:
        """Test snapshots with some missing resources raise with missing ids."""
        present = ResourceState(
            resource_id="i-present",
            resource_type="aws_instance",
            name="present",
            provider="aws",
            status=ResourceStatus.ACTIVE,
        )
        await repo.save_resource(present)

        snapshot = StateSnapshot(snapshot_id="snap-001")
        snapshot.add_resource(present)
        snapshot.add_resource(
            ResourceState(
                resource_id="i-missing",
                resource_type="aws_instance",
                name="missing",
                provider="aws",
                status=ResourceStatus.ACTIVE,
            )
        )
        await repo.save_snapshot(snapshot)

        with pytest.raises(MissingResourcesError) as excinfo:
            await repo.get_snapshot("snap-001")

        assert excinfo.value.snapshot_id == "snap-001"
        assert excinfo.value.missing_resource_ids == ["i-missing"]

    async def test_list_snapshots_empty(self, repo: StateRepository) -> None:
        """Test listing snapshots when empty."""
        result = await repo.list_snapshots()
        assert result == []

    async def test_list_snapshots(self, repo: StateRepository) -> None:
        """Test listing all snapshots."""
        s1 = StateSnapshot(snapshot_id="snap-001")
        s2 = StateSnapshot(snapshot_id="snap-002")

        await repo.save_snapshot(s1)
        await repo.save_snapshot(s2)

        result = await repo.list_snapshots()
        assert len(result) == 2

    async def test_list_snapshots_include_resources(self, repo: StateRepository) -> None:
        """Test listing snapshots with include_resources parameter."""
        # Create and save a resource
        resource = ResourceState(
            resource_id="i-12345",
            resource_type="aws_instance",
            name="web-server",
            provider="aws",
            status=ResourceStatus.ACTIVE,
        )
        await repo.save_resource(resource)

        # Create snapshot with the resource
        snapshot = StateSnapshot(snapshot_id="snap-001", description="Test")
        snapshot.add_resource(resource)
        await repo.save_snapshot(snapshot)

        # Without include_resources (default): no resources loaded
        result = await repo.list_snapshots()
        assert len(result) == 1
        assert result[0].resource_count == 0

        # With include_resources=True: resources are loaded
        result_with_resources = await repo.list_snapshots(include_resources=True)
        assert len(result_with_resources) == 1
        assert result_with_resources[0].resource_count == 1
        assert "i-12345" in result_with_resources[0].resources

    async def test_create_snapshot_from_current(self, repo: StateRepository) -> None:
        """Test creating a snapshot from current state."""
        # Add some resources first
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
            status=ResourceStatus.ACTIVE,
        )
        r2 = ResourceState(
            resource_id="i-002",
            resource_type="aws_instance",
            name="web-02",
            provider="aws",
            status=ResourceStatus.ACTIVE,
        )

        await repo.save_resource(r1)
        await repo.save_resource(r2)

        # Create snapshot
        snapshot = await repo.create_snapshot(description="Pre-deployment snapshot")

        assert snapshot.snapshot_id is not None
        assert snapshot.description == "Pre-deployment snapshot"
        assert snapshot.resource_count == 2

    async def test_create_snapshot_filtered_by_provider(self, repo: StateRepository) -> None:
        """Test creating a snapshot filtered by provider."""
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="aws-01",
            provider="aws",
        )
        r2 = ResourceState(
            resource_id="g-001",
            resource_type="compute_instance",
            name="gcp-01",
            provider="gcp",
        )

        await repo.save_resource(r1)
        await repo.save_resource(r2)

        snapshot = await repo.create_snapshot(provider="aws")

        assert snapshot.resource_count == 1
        assert "i-001" in snapshot.resources


class TestClearAll:
    """Test clear_all method."""

    @pytest.fixture
    async def repo(self, tmp_path: Path) -> StateRepository:
        """Create and initialize a repository."""
        db_path = tmp_path / "state.db"
        repo = StateRepository(db_path)
        await repo.initialize()
        return repo

    async def test_clear_all_resources(self, repo: StateRepository) -> None:
        """Test clearing all resources."""
        r1 = ResourceState(
            resource_id="i-001",
            resource_type="aws_instance",
            name="web-01",
            provider="aws",
        )
        await repo.save_resource(r1)

        s1 = StateSnapshot(snapshot_id="snap-001")
        await repo.save_snapshot(s1)

        await repo.clear_all()

        assert await repo.list_resources() == []
        assert await repo.list_snapshots() == []
