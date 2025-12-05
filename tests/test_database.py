"""Tests for database module."""

from __future__ import annotations

import pytest

from merlya.persistence.database import (
    Database,
    DatabaseError,
    IntegrityError,
    from_json,
    to_json,
)


class TestJsonHelpers:
    """Tests for JSON serialization helpers."""

    def test_to_json_dict(self) -> None:
        """Test dict serialization."""
        result = to_json({"key": "value"})
        assert result == '{"key": "value"}'

    def test_to_json_list(self) -> None:
        """Test list serialization."""
        result = to_json(["a", "b", "c"])
        assert result == '["a", "b", "c"]'

    def test_to_json_none(self) -> None:
        """Test None serialization."""
        result = to_json(None)
        assert result == "null"

    def test_from_json_dict(self) -> None:
        """Test dict deserialization."""
        result = from_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_from_json_list(self) -> None:
        """Test list deserialization."""
        result = from_json('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_from_json_none(self) -> None:
        """Test None deserialization."""
        result = from_json(None)
        assert result is None

    def test_from_json_empty(self) -> None:
        """Test empty string deserialization."""
        result = from_json("")
        assert result is None


class TestDatabase:
    """Tests for Database class."""

    @pytest.mark.asyncio
    async def test_connect_creates_tables(self, database: Database) -> None:
        """Test that connect creates required tables."""
        async with await database.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            rows = await cursor.fetchall()
            tables = {row["name"] for row in rows}

        assert "hosts" in tables
        assert "variables" in tables
        assert "conversations" in tables
        assert "config" in tables

    @pytest.mark.asyncio
    async def test_transaction_commit(self, database: Database) -> None:
        """Test transaction commits on success."""
        async with database.transaction():
            await database.execute(
                "INSERT INTO variables (name, value) VALUES (?, ?)",
                ("test_key", "test_value"),
            )

        async with await database.execute(
            "SELECT value FROM variables WHERE name = ?", ("test_key",)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["value"] == "test_value"

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, database: Database) -> None:
        """Test transaction rollback on error."""
        with pytest.raises(ValueError):
            async with database.transaction():
                await database.execute(
                    "INSERT INTO variables (name, value) VALUES (?, ?)",
                    ("rollback_key", "rollback_value"),
                )
                raise ValueError("Intentional error")

        async with await database.execute(
            "SELECT value FROM variables WHERE name = ?", ("rollback_key",)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is None

    @pytest.mark.asyncio
    async def test_integrity_error(self, database: Database) -> None:
        """Test IntegrityError on duplicate key."""
        await database.execute(
            "INSERT INTO variables (name, value) VALUES (?, ?)",
            ("unique_key", "value1"),
        )
        await database.commit()

        with pytest.raises(IntegrityError):
            await database.execute(
                "INSERT INTO variables (name, value) VALUES (?, ?)",
                ("unique_key", "value2"),
            )
