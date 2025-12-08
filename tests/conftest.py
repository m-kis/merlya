"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from merlya.persistence.database import Database

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Use pytest-asyncio's built-in event loop management
# See: https://pytest-asyncio.readthedocs.io/en/latest/concepts.html
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Return the event loop policy to use for tests."""
    return asyncio.DefaultEventLoopPolicy()


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
