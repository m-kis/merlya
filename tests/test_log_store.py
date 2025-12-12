"""
Tests for Log Store functionality.

Tests store_raw_log, get_raw_log, get_raw_log_slice operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from merlya.persistence.database import Database
from merlya.tools.logs.store import (
    LogRef,
    RawLogEntry,
    cleanup_expired_logs,
    get_logs_by_host,
    get_raw_log,
    get_raw_log_slice,
    store_raw_log,
)


@pytest.fixture
async def test_db(tmp_path):
    """Create a test database."""
    db_path = tmp_path / "test.db"
    db = Database(path=db_path)
    await db.connect()
    yield db
    await db.close()


async def create_test_host(db: Database, name: str) -> str:
    """Helper to create a test host and return its ID."""
    host_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO hosts (id, name, hostname, port, tags, metadata)
        VALUES (?, ?, ?, ?, '[]', '{}')
        """,
        (host_id, name, f"{name}.example.com", 22),
    )
    await db.connection.commit()
    return host_id


class TestStoreRawLog:
    """Tests for store_raw_log function."""

    @pytest.mark.asyncio
    async def test_store_simple_log(self, test_db):
        """Test storing a simple log."""
        output = "Line 1\nLine 2\nLine 3"
        log_ref = await store_raw_log(
            db=test_db,
            command="echo test",
            output=output,
        )

        assert isinstance(log_ref, LogRef)
        assert log_ref.command == "echo test"
        assert log_ref.line_count == 3
        assert log_ref.byte_size == len(output.encode())
        assert log_ref.host_id is None

    @pytest.mark.asyncio
    async def test_store_log_with_host(self, test_db):
        """Test storing log with host ID."""
        # Create host first (FK constraint)
        host_id = await create_test_host(test_db, "web-01")

        log_ref = await store_raw_log(
            db=test_db,
            command="journalctl -n 100",
            output="log output here",
            host_id=host_id,
            exit_code=0,
        )

        assert log_ref.host_id == host_id

    @pytest.mark.asyncio
    async def test_store_large_log(self, test_db):
        """Test storing a large log."""
        lines = [f"Line {i}: Some log content here" for i in range(1000)]
        output = "\n".join(lines)

        log_ref = await store_raw_log(
            db=test_db,
            command="cat /var/log/syslog",
            output=output,
        )

        assert log_ref.line_count == 1000
        assert log_ref.byte_size > 30000

    @pytest.mark.asyncio
    async def test_store_empty_log(self, test_db):
        """Test storing an empty log."""
        log_ref = await store_raw_log(
            db=test_db,
            command="cat /dev/null",
            output="",
        )

        assert log_ref.line_count == 0
        assert log_ref.byte_size == 0


class TestGetRawLog:
    """Tests for get_raw_log function."""

    @pytest.mark.asyncio
    async def test_get_existing_log(self, test_db):
        """Test retrieving an existing log."""
        output = "Test log content\nSecond line"
        log_ref = await store_raw_log(
            db=test_db,
            command="test",
            output=output,
            exit_code=0,
        )

        entry = await get_raw_log(test_db, log_ref.id)

        assert entry is not None
        assert isinstance(entry, RawLogEntry)
        assert entry.output == output
        assert entry.exit_code == 0
        assert entry.line_count == 2

    @pytest.mark.asyncio
    async def test_get_nonexistent_log(self, test_db):
        """Test retrieving non-existent log returns None."""
        entry = await get_raw_log(test_db, "nonexistent-id")
        assert entry is None


class TestGetRawLogSlice:
    """Tests for get_raw_log_slice function."""

    @pytest.fixture
    async def stored_log(self, test_db):
        """Store a test log with 100 lines."""
        lines = [f"Line {i:03d}: Content" for i in range(1, 101)]
        output = "\n".join(lines)
        return await store_raw_log(
            db=test_db,
            command="test",
            output=output,
        )

    @pytest.mark.asyncio
    async def test_slice_around_line(self, test_db, stored_log):
        """Test slicing around a specific line."""
        result = await get_raw_log_slice(
            test_db,
            stored_log.id,
            around_line=50,
            window=10,
        )

        assert result is not None
        sliced, start, end = result
        assert start == 40  # 50 - 10
        assert end == 60  # 50 + 10
        assert "Line 050" in sliced
        assert "Line 040" in sliced
        assert "Line 060" in sliced

    @pytest.mark.asyncio
    async def test_slice_explicit_range(self, test_db, stored_log):
        """Test slicing with explicit start/end."""
        result = await get_raw_log_slice(
            test_db,
            stored_log.id,
            start_line=10,
            end_line=20,
        )

        assert result is not None
        sliced, start, end = result
        assert start == 10
        assert end == 20
        assert "Line 010" in sliced
        assert "Line 020" in sliced
        assert "Line 021" not in sliced

    @pytest.mark.asyncio
    async def test_slice_at_beginning(self, test_db, stored_log):
        """Test slicing at the beginning of log."""
        result = await get_raw_log_slice(
            test_db,
            stored_log.id,
            around_line=5,
            window=10,
        )

        assert result is not None
        sliced, start, _end = result
        assert start == 1  # Can't go below 1
        assert "Line 001" in sliced

    @pytest.mark.asyncio
    async def test_slice_at_end(self, test_db, stored_log):
        """Test slicing at the end of log."""
        result = await get_raw_log_slice(
            test_db,
            stored_log.id,
            around_line=95,
            window=10,
        )

        assert result is not None
        sliced, _start, _end = result
        assert "Line 100" in sliced

    @pytest.mark.asyncio
    async def test_slice_nonexistent_log(self, test_db):
        """Test slicing non-existent log returns None."""
        result = await get_raw_log_slice(
            test_db,
            "nonexistent",
            around_line=50,
        )
        assert result is None


class TestCleanupExpiredLogs:
    """Tests for cleanup_expired_logs function."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, test_db):
        """Test that expired logs are removed."""
        # Store a log with 0 TTL (expires immediately)
        await store_raw_log(
            db=test_db,
            command="old",
            output="old content",
            ttl_hours=0,
        )

        # Store a fresh log
        fresh = await store_raw_log(
            db=test_db,
            command="fresh",
            output="fresh content",
            ttl_hours=24,
        )

        # Force expire the old log by updating directly
        await test_db.execute(
            "UPDATE raw_logs SET expires_at = ? WHERE command = ?",
            (datetime.now() - timedelta(hours=1), "old"),
        )
        await test_db.connection.commit()

        # Cleanup
        deleted = await cleanup_expired_logs(test_db)

        assert deleted == 1

        # Fresh log should still exist
        entry = await get_raw_log(test_db, fresh.id)
        assert entry is not None


class TestGetLogsByHost:
    """Tests for get_logs_by_host function."""

    @pytest.mark.asyncio
    async def test_get_logs_by_host(self, test_db):
        """Test retrieving logs by host."""
        # Create hosts first
        web_host_id = await create_test_host(test_db, "web-01")
        db_host_id = await create_test_host(test_db, "db-01")

        # Store logs for different hosts
        await store_raw_log(test_db, "cmd1", "output1", host_id=web_host_id)
        await store_raw_log(test_db, "cmd2", "output2", host_id=web_host_id)
        await store_raw_log(test_db, "cmd3", "output3", host_id=db_host_id)

        logs = await get_logs_by_host(test_db, web_host_id)

        assert len(logs) == 2
        assert all(log.host_id == web_host_id for log in logs)

    @pytest.mark.asyncio
    async def test_get_logs_by_host_with_limit(self, test_db):
        """Test limit parameter."""
        host_id = await create_test_host(test_db, "host-01")

        for i in range(5):
            await store_raw_log(test_db, f"cmd{i}", f"output{i}", host_id=host_id)

        logs = await get_logs_by_host(test_db, host_id, limit=3)

        assert len(logs) == 3

    @pytest.mark.asyncio
    async def test_get_logs_empty_host(self, test_db):
        """Test getting logs for host with no logs."""
        logs = await get_logs_by_host(test_db, "nonexistent-host")
        assert logs == []
