"""
Merlya Provisioners State - Tracker.

High-level state tracking interface.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.provisioners.state.models import (
    DriftResult,
    ResourceState,
    ResourceStatus,
    StateSnapshot,
)
from merlya.provisioners.state.repository import MissingResourcesError, StateRepository

if TYPE_CHECKING:
    from pathlib import Path

    from merlya.core.context import SharedContext


class StateTracker:
    """
    High-level state tracking interface.

    Provides methods for tracking resource lifecycle, detecting drift,
    and managing state snapshots.
    """

    def __init__(
        self,
        repository: StateRepository | None = None,
        db_path: Path | None = None,
        ctx: SharedContext | None = None,
    ):
        """
        Initialize the state tracker.

        Args:
            repository: Existing repository instance.
            db_path: Path to SQLite database (creates new repository).
            ctx: SharedContext for configuration.
        """
        if repository is not None:
            self._repo = repository
        else:
            self._repo = StateRepository(db_path=db_path, ctx=ctx)

    @property
    def repository(self) -> StateRepository:
        """Get the underlying repository."""
        return self._repo

    # Resource Lifecycle Methods

    async def track_resource(
        self,
        resource_id: str,
        resource_type: str,
        name: str,
        provider: str,
        expected_config: dict[str, Any],
        region: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> ResourceState:
        """
        Start tracking a new resource.

        Args:
            resource_id: Unique resource identifier.
            resource_type: Type of resource (e.g., 'aws_instance').
            name: Human-readable name.
            provider: Cloud provider.
            expected_config: Expected configuration.
            region: Optional region/zone.
            tags: Optional resource tags.

        Returns:
            The created ResourceState.
        """
        resource = ResourceState(
            resource_id=resource_id,
            resource_type=resource_type,
            name=name,
            provider=provider,
            region=region,
            status=ResourceStatus.PENDING,
            expected_config=expected_config,
            tags=tags or {},
        )

        await self._repo.save_resource(resource)
        logger.debug(f"Started tracking resource: {resource_id}")
        return resource

    async def update_status(
        self,
        resource_id: str,
        status: ResourceStatus,
        actual_config: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> ResourceState | None:
        """
        Update a resource's status.

        Args:
            resource_id: Resource to update.
            status: New status.
            actual_config: Optional actual configuration from provider.
            outputs: Optional resource outputs.

        Returns:
            Updated ResourceState or None if not found.
        """
        resource = await self._repo.get_resource(resource_id)
        if resource is None:
            logger.warning(f"Resource not found for status update: {resource_id}")
            return None

        # Save previous state for rollback if transitioning to updating
        if status == ResourceStatus.UPDATING:
            resource.save_for_rollback()

        resource.status = status
        resource.mark_updated()

        if actual_config is not None:
            resource.actual_config = actual_config

        if outputs is not None:
            resource.outputs = outputs

        await self._repo.save_resource(resource)
        logger.debug(f"Updated resource {resource_id} status to {status.value}")
        return resource

    async def mark_created(
        self,
        resource_id: str,
        actual_config: dict[str, Any],
        outputs: dict[str, Any] | None = None,
    ) -> ResourceState | None:
        """Mark a resource as successfully created."""
        return await self.update_status(
            resource_id=resource_id,
            status=ResourceStatus.ACTIVE,
            actual_config=actual_config,
            outputs=outputs,
        )

    async def mark_updated(
        self,
        resource_id: str,
        actual_config: dict[str, Any],
        outputs: dict[str, Any] | None = None,
    ) -> ResourceState | None:
        """Mark a resource as successfully updated."""
        return await self.update_status(
            resource_id=resource_id,
            status=ResourceStatus.ACTIVE,
            actual_config=actual_config,
            outputs=outputs,
        )

    async def mark_deleted(self, resource_id: str) -> ResourceState | None:
        """Mark a resource as deleted."""
        return await self.update_status(
            resource_id=resource_id,
            status=ResourceStatus.DELETED,
        )

    async def mark_failed(
        self,
        resource_id: str,
        error: str | None = None,
    ) -> ResourceState | None:
        """Mark a resource operation as failed."""
        resource = await self.update_status(
            resource_id=resource_id,
            status=ResourceStatus.FAILED,
        )
        if resource and error:
            resource.outputs["error"] = error
            await self._repo.save_resource(resource)
        return resource

    async def untrack_resource(self, resource_id: str) -> bool:
        """
        Stop tracking a resource (removes from state).

        Args:
            resource_id: Resource to untrack.

        Returns:
            True if resource was removed, False if not found.
        """
        result = await self._repo.delete_resource(resource_id)
        if result:
            logger.debug(f"Untracked resource: {resource_id}")
        return result

    # Query Methods

    async def get_resource(self, resource_id: str) -> ResourceState | None:
        """Get a resource by ID."""
        return await self._repo.get_resource(resource_id)

    async def list_resources(
        self,
        provider: str | None = None,
        status: ResourceStatus | None = None,
        resource_type: str | None = None,
    ) -> list[ResourceState]:
        """List resources with optional filters."""
        return await self._repo.list_resources(
            provider=provider,
            status=status,
            resource_type=resource_type,
        )

    async def list_active_resources(
        self,
        provider: str | None = None,
    ) -> list[ResourceState]:
        """List all active resources."""
        return await self._repo.list_resources(
            provider=provider,
            status=ResourceStatus.ACTIVE,
        )

    # Drift Detection

    async def check_drift(
        self,
        resource_id: str,
        actual_config: dict[str, Any],
    ) -> DriftResult:
        """
        Check if a resource has drifted from expected state.

        Args:
            resource_id: Resource to check.
            actual_config: Current configuration from provider.

        Returns:
            DriftResult with status and differences.
        """
        resource = await self._repo.get_resource(resource_id)
        if resource is None:
            return DriftResult.from_error(resource_id, "Resource not found in state")

        # Update actual config and check time
        resource.actual_config = actual_config
        resource.mark_checked()
        await self._repo.save_resource(resource)

        # Compare expected vs actual
        if not resource.expected_config:
            return DriftResult.no_drift(resource_id)

        differences = self._compare_configs(
            resource.expected_config,
            actual_config,
        )

        if differences:
            logger.warning(
                f"Drift detected for resource {resource_id}: {len(differences)} differences"
            )
            return DriftResult.drifted(resource_id, differences)

        return DriftResult.no_drift(resource_id)

    async def check_all_drift(
        self,
        provider: str | None = None,
        actual_configs: dict[str, dict[str, Any]] | None = None,
    ) -> list[DriftResult]:
        """
        Check drift for all active resources.

        Args:
            provider: Optional provider filter.
            actual_configs: Mapping of resource_id -> actual config.
                           If not provided, resources are marked as MISSING.

        Returns:
            List of DriftResults.
        """
        resources = await self.list_active_resources(provider=provider)
        results = []

        for resource in resources:
            if actual_configs and resource.resource_id in actual_configs:
                result = await self.check_drift(
                    resource.resource_id,
                    actual_configs[resource.resource_id],
                )
            else:
                # Resource not found in actual configs - might be missing
                result = DriftResult.missing(resource.resource_id)

            results.append(result)

        return results

    def _compare_configs(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> dict[str, tuple[Any, Any]]:
        """
        Compare expected and actual configurations.

        Returns mapping of field -> (expected_value, actual_value) for differences.
        """
        differences: dict[str, tuple[Any, Any]] = {}

        all_keys = set(expected.keys()) | set(actual.keys())

        for key in all_keys:
            expected_val = expected.get(key)
            actual_val = actual.get(key)

            if expected_val != actual_val:
                differences[key] = (expected_val, actual_val)

        return differences

    # Snapshot Management

    async def create_snapshot(
        self,
        provider: str | None = None,
        session_id: str | None = None,
        description: str | None = None,
    ) -> StateSnapshot:
        """
        Create a snapshot of current state.

        Args:
            provider: Optional provider filter.
            session_id: Optional session identifier.
            description: Optional description.

        Returns:
            Created StateSnapshot.
        """
        snapshot = await self._repo.create_snapshot(
            provider=provider,
            session_id=session_id,
            description=description,
        )
        logger.info(
            f"Created state snapshot: {snapshot.snapshot_id} ({snapshot.resource_count} resources)"
        )
        return snapshot

    async def get_snapshot(self, snapshot_id: str) -> StateSnapshot | None:
        """Get a snapshot by ID."""
        return await self._repo.get_snapshot(snapshot_id)

    async def list_snapshots(
        self,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[StateSnapshot]:
        """List recent snapshots."""
        return await self._repo.list_snapshots(provider=provider, limit=limit)

    async def restore_snapshot(
        self,
        snapshot_id: str,
    ) -> StateSnapshot | None:
        """
        Restore state from a snapshot.

        This overwrites current state with snapshot data.

        Args:
            snapshot_id: Snapshot to restore.

        Returns:
            The restored snapshot or None if not found.
        """
        try:
            snapshot = await self._repo.get_snapshot(snapshot_id)
        except MissingResourcesError as e:
            logger.error(
                f"Cannot restore snapshot {e.snapshot_id}: missing resources {e.missing_resource_ids}"
            )
            raise
        if snapshot is None:
            logger.warning(f"Snapshot not found: {snapshot_id}")
            return None

        # Save each resource from snapshot
        for resource in snapshot.resources.values():
            resource.mark_updated()
            await self._repo.save_resource(resource)

        logger.info(f"Restored state from snapshot: {snapshot_id}")
        return snapshot

    # Utility Methods

    async def get_rollback_config(self, resource_id: str) -> dict[str, Any] | None:
        """Get the previous configuration for rollback."""
        resource = await self._repo.get_resource(resource_id)
        if resource is None:
            return None
        return resource.previous_config

    async def clear_all(self) -> None:
        """Clear all state data (for testing)."""
        await self._repo.clear_all()
        logger.warning("Cleared all state data")
