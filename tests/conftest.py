"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest

from merlya.persistence.database import Database


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def temp_db_path() -> AsyncGenerator[Path, None]:
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
async def database(temp_db_path: Path) -> AsyncGenerator[Database, None]:
    """Create a test database."""
    db = Database(temp_db_path)
    await db.connect()
    yield db
    await db.close()
    Database.reset_instance()
