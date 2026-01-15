"""
Merlya Provisioners State - Repository.

SQLite persistence for resource state.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
from loguru import logger

from merlya.provisioners.state.models import (
    ResourceState,
    ResourceStatus,
    StateSnapshot,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class MissingResourcesError(LookupError):
    """Raised when a snapshot references resources that are not present."""

    def __init__(self, snapshot_id: str, missing_resource_ids: list[str]):
        self.snapshot_id = snapshot_id
        self.missing_resource_ids = missing_resource_ids
        super().__init__(f"Snapshot {snapshot_id} is missing resources: {missing_resource_ids}")


class StateRepository:
    """
    SQLite-based state persistence.

    Stores resource states and snapshots in a local database.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path | None = None, ctx: SharedContext | None = None):
        """
        Initialize the repository.

        Args:
            db_path: Path to SQLite database. If None, uses default from context.
            ctx: SharedContext for configuration access.
        """
        if db_path is None and ctx is not None:
            db_path = ctx.config.general.data_dir / "provisioner_state.db"
        elif db_path is None:
            db_path = Path.home() / ".merlya" / "provisioner_state.db"

        self._db_path = db_path
        self._initialized = False

    @property
    def db_path(self) -> Path:
        """Get the database path."""
        return self._db_path

    async def initialize(self) -> None:
        """Initialize the database schema."""
        if self._initialized:
            return

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._db_path) as db:
            # Create schema version table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)

            # Check current version
            cursor = await db.execute("SELECT version FROM schema_version LIMIT 1")
            row = await cursor.fetchone()
            current_version = row[0] if row else 0

            if current_version < self.SCHEMA_VERSION:
                await self._migrate(db, current_version)

            await db.commit()

        self._initialized = True
        logger.debug(f"🗄️ State repository initialized at {self._db_path}")

    async def _migrate(self, db: aiosqlite.Connection, from_version: int) -> None:
        """Run database migrations."""
        if from_version < 1:
            # Initial schema
            await db.execute("""
                CREATE TABLE IF NOT EXISTS resources (
                    resource_id TEXT PRIMARY KEY,
                    resource_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    region TEXT,
                    status TEXT NOT NULL,
                    expected_config TEXT NOT NULL,
                    actual_config TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    outputs TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    previous_config TEXT
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_resources_provider
                ON resources(provider)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_resources_status
                ON resources(status)
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    provider TEXT,
                    session_id TEXT,
                    resource_ids TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    description TEXT
                )
            """)

            # Update schema version
            await db.execute("DELETE FROM schema_version")
            await db.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (self.SCHEMA_VERSION,),
            )

            logger.info("✅ Migrated state database to version 1")

    async def save_resource(self, resource: ResourceState) -> None:
        """Save or update a resource state."""
        await self.initialize()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO resources (
                    resource_id, resource_type, name, provider, region,
                    status, expected_config, actual_config, tags, outputs,
                    created_at, updated_at, last_checked_at, previous_config
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource.resource_id,
                    resource.resource_type,
                    resource.name,
                    resource.provider,
                    resource.region,
                    resource.status.value,
                    json.dumps(resource.expected_config),
                    json.dumps(resource.actual_config),
                    json.dumps(resource.tags),
                    json.dumps(resource.outputs),
                    resource.created_at.isoformat(),
                    resource.updated_at.isoformat(),
                    resource.last_checked_at.isoformat() if resource.last_checked_at else None,
                    json.dumps(resource.previous_config) if resource.previous_config else None,
                ),
            )
            await db.commit()

    async def get_resource(self, resource_id: str) -> ResourceState | None:
        """Get a resource by ID."""
        await self.initialize()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM resources WHERE resource_id = ?",
                (resource_id,),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

            return self._row_to_resource(row)

    async def delete_resource(self, resource_id: str) -> bool:
        """Delete a resource by ID."""
        await self.initialize()

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM resources WHERE resource_id = ?",
                (resource_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    def _validate_filter_param(self, name: str, value: str | None) -> None:
        """Validate a filter parameter against injection attempts."""
        if value is None:
            return
        # Allow alphanumeric, underscores, hyphens, and dots
        if not re.match(r"^[a-zA-Z0-9_.-]+$", value):
            raise ValueError(f"Invalid {name}: {value}")

    async def list_resources(
        self,
        provider: str | None = None,
        status: ResourceStatus | None = None,
        resource_type: str | None = None,
    ) -> list[ResourceState]:
        """List resources with optional filters."""
        await self.initialize()

        # Validate inputs
        self._validate_filter_param("provider", provider)
        self._validate_filter_param("resource_type", resource_type)

        query = "SELECT * FROM resources WHERE 1=1"
        params: list[Any] = []

        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if resource_type:
            query += " AND resource_type = ?"
            params.append(resource_type)

        query += " ORDER BY updated_at DESC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            return [self._row_to_resource(row) for row in rows]

    async def save_snapshot(self, snapshot: StateSnapshot) -> None:
        """
        Save a state snapshot with transaction rollback on error.

        Note: Snapshots store references to resources via resource_ids.
        Resources should be saved separately via save_resource() before
        creating a snapshot. This method only saves snapshot metadata,
        not resource data, to avoid overwriting live resource states.
        """
        await self.initialize()

        resource_ids = list(snapshot.resources.keys())

        async with aiosqlite.connect(self._db_path) as db:
            try:
                # Save snapshot metadata only (resources are referenced, not copied)
                await db.execute(
                    """
                    INSERT OR REPLACE INTO snapshots (
                        snapshot_id, provider, session_id, resource_ids,
                        created_at, description
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.provider,
                        snapshot.session_id,
                        json.dumps(resource_ids),
                        snapshot.created_at.isoformat(),
                        snapshot.description,
                    ),
                )

                await db.commit()
                logger.debug(
                    f"🗄️ Saved snapshot {snapshot.snapshot_id} with {len(resource_ids)} resources"
                )
            except Exception as e:
                await db.rollback()
                logger.error(f"❌ Failed to save snapshot {snapshot.snapshot_id}: {e}")
                raise

    async def get_snapshot(self, snapshot_id: str) -> StateSnapshot | None:
        """Get a snapshot by ID.

        Raises:
            MissingResourcesError: If the snapshot references resources that cannot be loaded.
        """
        await self.initialize()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

            # Load resources
            resource_ids = json.loads(row["resource_ids"])
            resources: dict[str, ResourceState] = {}
            missing_resource_ids: list[str] = []

            for resource_id in resource_ids:
                resource = await self.get_resource(resource_id)
                if resource is not None:
                    resources[resource_id] = resource
                else:
                    missing_resource_ids.append(resource_id)

            if missing_resource_ids:
                raise MissingResourcesError(
                    snapshot_id=row["snapshot_id"],
                    missing_resource_ids=missing_resource_ids,
                )

            return StateSnapshot(
                snapshot_id=row["snapshot_id"],
                provider=row["provider"],
                session_id=row["session_id"],
                resources=resources,
                created_at=self._parse_datetime(row["created_at"]),
                description=row["description"],
            )

    async def list_snapshots(
        self,
        provider: str | None = None,
        limit: int = 100,
        include_resources: bool = False,
    ) -> list[StateSnapshot]:
        """
        List recent snapshots.

        Args:
            provider: Filter by provider.
            limit: Maximum number of snapshots to return.
            include_resources: If True, load full resource data for each snapshot.
                             If False (default), returns lightweight snapshot metadata
                             for better performance. Use get_snapshot() to load full
                             resource data for specific snapshots.
        """
        await self.initialize()

        # Validate inputs
        self._validate_filter_param("provider", provider)

        query = "SELECT * FROM snapshots WHERE 1=1"
        params: list[Any] = []

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            snapshots = []
            for row in rows:
                resources: dict[str, ResourceState] = {}

                # Only load resources if explicitly requested
                if include_resources:
                    resource_ids = json.loads(row["resource_ids"])
                    missing_resource_ids: list[str] = []
                    for resource_id in resource_ids:
                        resource = await self.get_resource(resource_id)
                        if resource is not None:
                            resources[resource_id] = resource
                        else:
                            missing_resource_ids.append(resource_id)

                    if missing_resource_ids:
                        logger.warning(
                            f"⚠️ Snapshot {row['snapshot_id']}: missing resources {missing_resource_ids}"
                        )

                snapshots.append(
                    StateSnapshot(
                        snapshot_id=row["snapshot_id"],
                        provider=row["provider"],
                        session_id=row["session_id"],
                        resources=resources,
                        created_at=self._parse_datetime(row["created_at"]),
                        description=row["description"],
                    )
                )

            return snapshots

    async def create_snapshot(
        self,
        provider: str | None = None,
        session_id: str | None = None,
        description: str | None = None,
    ) -> StateSnapshot:
        """Create a snapshot of current resources."""
        await self.initialize()

        # Get all resources (optionally filtered by provider)
        resources = await self.list_resources(provider=provider)

        snapshot = StateSnapshot(
            snapshot_id=str(uuid.uuid4()),
            provider=provider,
            session_id=session_id,
            resources={r.resource_id: r for r in resources},
            description=description,
        )

        await self.save_snapshot(snapshot)
        return snapshot

    async def clear_all(self) -> None:
        """Clear all state data (for testing)."""
        await self.initialize()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM resources")
            await db.execute("DELETE FROM snapshots")
            await db.commit()

    def _parse_datetime(self, value: str) -> datetime:
        """Parse ISO datetime string with timezone awareness."""
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    def _row_to_resource(self, row: aiosqlite.Row) -> ResourceState:
        """Convert a database row to ResourceState."""
        return ResourceState(
            resource_id=row["resource_id"],
            resource_type=row["resource_type"],
            name=row["name"],
            provider=row["provider"],
            region=row["region"],
            status=ResourceStatus(row["status"]),
            expected_config=json.loads(row["expected_config"]),
            actual_config=json.loads(row["actual_config"]),
            tags=json.loads(row["tags"]),
            outputs=json.loads(row["outputs"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            last_checked_at=(
                self._parse_datetime(row["last_checked_at"]) if row["last_checked_at"] else None
            ),
            previous_config=(
                json.loads(row["previous_config"]) if row["previous_config"] else None
            ),
        )
