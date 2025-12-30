"""
Merlya Provisioners State - Repository.

SQLite persistence for resource state.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from loguru import logger

from merlya.provisioners.state.models import (
    ResourceState,
    ResourceStatus,
    StateSnapshot,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


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
            db_path = ctx.config_dir / "provisioner_state.db"
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
        logger.debug(f"State repository initialized at {self._db_path}")

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

            logger.info("Migrated state database to version 1")

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

    async def list_resources(
        self,
        provider: str | None = None,
        status: ResourceStatus | None = None,
        resource_type: str | None = None,
    ) -> list[ResourceState]:
        """List resources with optional filters."""
        await self.initialize()

        query = "SELECT * FROM resources WHERE 1=1"
        params: list[str] = []

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
        """Save a state snapshot."""
        await self.initialize()

        resource_ids = list(snapshot.resources.keys())

        async with aiosqlite.connect(self._db_path) as db:
            # Save snapshot metadata
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

            # Save all resources
            for resource in snapshot.resources.values():
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

    async def get_snapshot(self, snapshot_id: str) -> StateSnapshot | None:
        """Get a snapshot by ID."""
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

            for resource_id in resource_ids:
                resource = await self.get_resource(resource_id)
                if resource:
                    resources[resource_id] = resource

            return StateSnapshot(
                snapshot_id=row["snapshot_id"],
                provider=row["provider"],
                session_id=row["session_id"],
                resources=resources,
                created_at=datetime.fromisoformat(row["created_at"]),
                description=row["description"],
            )

    async def list_snapshots(
        self,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[StateSnapshot]:
        """List recent snapshots."""
        await self.initialize()

        query = "SELECT * FROM snapshots WHERE 1=1"
        params: list[str | int] = []

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
                resource_ids = json.loads(row["resource_ids"])
                resources: dict[str, ResourceState] = {}

                for resource_id in resource_ids:
                    resource = await self.get_resource(resource_id)
                    if resource:
                        resources[resource_id] = resource

                snapshots.append(
                    StateSnapshot(
                        snapshot_id=row["snapshot_id"],
                        provider=row["provider"],
                        session_id=row["session_id"],
                        resources=resources,
                        created_at=datetime.fromisoformat(row["created_at"]),
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
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_checked_at=(
                datetime.fromisoformat(row["last_checked_at"])
                if row["last_checked_at"]
                else None
            ),
            previous_config=(
                json.loads(row["previous_config"])
                if row["previous_config"]
                else None
            ),
        )
