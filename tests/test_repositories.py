"""Tests for repository classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from merlya.persistence.models import Host
from merlya.persistence.repositories import HostRepository, VariableRepository

if TYPE_CHECKING:
    from merlya.persistence.database import Database


class TestHostRepository:
    """Tests for HostRepository."""

    @pytest.fixture
    async def host_repo(self, database: Database) -> HostRepository:
        """Create host repository."""
        return HostRepository(database)

    @pytest.mark.asyncio
    async def test_create_host(self, host_repo: HostRepository) -> None:
        """Test host creation."""
        host = Host(name="test-server", hostname="192.168.1.1")
        created = await host_repo.create(host)

        assert created.id == host.id
        assert created.name == "test-server"
        assert created.hostname == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_create_duplicate_name_raises(self, host_repo: HostRepository) -> None:
        """Test that duplicate name raises ValueError."""
        host1 = Host(name="duplicate", hostname="192.168.1.1")
        await host_repo.create(host1)

        host2 = Host(name="duplicate", hostname="192.168.1.2")
        with pytest.raises(ValueError, match="must be unique"):
            await host_repo.create(host2)

    @pytest.mark.asyncio
    async def test_get_by_name(self, host_repo: HostRepository) -> None:
        """Test get host by name."""
        host = Host(name="lookup-test", hostname="192.168.1.1")
        await host_repo.create(host)

        found = await host_repo.get_by_name("lookup-test")
        assert found is not None
        assert found.name == "lookup-test"

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, host_repo: HostRepository) -> None:
        """Test get non-existent host returns None."""
        found = await host_repo.get_by_name("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_by_tag(self, host_repo: HostRepository) -> None:
        """Test get hosts by tag."""
        host1 = Host(name="web-1", hostname="192.168.1.1", tags=["web", "prod"])
        host2 = Host(name="web-2", hostname="192.168.1.2", tags=["web", "staging"])
        host3 = Host(name="db-1", hostname="192.168.1.3", tags=["db", "prod"])

        await host_repo.create(host1)
        await host_repo.create(host2)
        await host_repo.create(host3)

        web_hosts = await host_repo.get_by_tag("web")
        assert len(web_hosts) == 2
        assert all(h.name.startswith("web") for h in web_hosts)

        prod_hosts = await host_repo.get_by_tag("prod")
        assert len(prod_hosts) == 2

    @pytest.mark.asyncio
    async def test_get_by_tag_invalid_format(self, host_repo: HostRepository) -> None:
        """Test that invalid tag format returns empty list."""
        result = await host_repo.get_by_tag("invalid<tag>")
        assert result == []

        result = await host_repo.get_by_tag("")
        assert result == []

    @pytest.mark.asyncio
    async def test_update_host(self, host_repo: HostRepository) -> None:
        """Test host update."""
        host = Host(name="update-test", hostname="192.168.1.1", port=22)
        await host_repo.create(host)

        host.port = 2222
        host.username = "admin"
        updated = await host_repo.update(host)

        assert updated.port == 2222
        assert updated.username == "admin"

    @pytest.mark.asyncio
    async def test_delete_host(self, host_repo: HostRepository) -> None:
        """Test host deletion."""
        host = Host(name="delete-test", hostname="192.168.1.1")
        await host_repo.create(host)

        deleted = await host_repo.delete(host.id)
        assert deleted is True

        found = await host_repo.get_by_id(host.id)
        assert found is None

    @pytest.mark.asyncio
    async def test_count(self, host_repo: HostRepository) -> None:
        """Test host count."""
        assert await host_repo.count() == 0

        await host_repo.create(Host(name="count-1", hostname="192.168.1.1"))
        await host_repo.create(Host(name="count-2", hostname="192.168.1.2"))

        assert await host_repo.count() == 2

    @pytest.mark.asyncio
    async def test_row_to_host_with_null_elevation_method(
        self, host_repo: HostRepository, database: Database
    ) -> None:
        """Test that NULL elevation_method in database defaults to NONE.

        This tests the fix for hosts created before elevation_method was added.
        """
        from merlya.persistence.models import ElevationMethod

        # Create a host with explicit elevation_method
        host = Host(name="legacy-host", hostname="192.168.1.100")
        await host_repo.create(host)

        # Manually set elevation_method to NULL in database (simulating legacy data)
        await database.execute(
            "UPDATE hosts SET elevation_method = NULL WHERE name = ?",
            ("legacy-host",),
        )

        # Now fetch the host - should not raise validation error
        fetched = await host_repo.get_by_name("legacy-host")
        assert fetched is not None
        assert fetched.name == "legacy-host"
        # Should default to NONE when NULL in database
        assert fetched.elevation_method == ElevationMethod.NONE


class TestVariableRepository:
    """Tests for VariableRepository."""

    @pytest.fixture
    async def var_repo(self, database: Database) -> VariableRepository:
        """Create variable repository."""
        return VariableRepository(database)

    @pytest.mark.asyncio
    async def test_set_variable(self, var_repo: VariableRepository) -> None:
        """Test setting a variable."""
        var = await var_repo.set("my_key", "my_value")

        assert var.name == "my_key"
        assert var.value == "my_value"
        assert var.is_env is False

    @pytest.mark.asyncio
    async def test_set_env_variable(self, var_repo: VariableRepository) -> None:
        """Test setting an env variable."""
        var = await var_repo.set("PATH", "/usr/bin", is_env=True)

        assert var.is_env is True

    @pytest.mark.asyncio
    async def test_set_updates_existing(self, var_repo: VariableRepository) -> None:
        """Test that set updates existing variable."""
        await var_repo.set("update_key", "value1")
        await var_repo.set("update_key", "value2")

        var = await var_repo.get("update_key")
        assert var is not None
        assert var.value == "value2"

    @pytest.mark.asyncio
    async def test_get_variable(self, var_repo: VariableRepository) -> None:
        """Test getting a variable."""
        await var_repo.set("get_key", "get_value")

        var = await var_repo.get("get_key")
        assert var is not None
        assert var.value == "get_value"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, var_repo: VariableRepository) -> None:
        """Test getting non-existent variable returns None."""
        var = await var_repo.get("nonexistent")
        assert var is None

    @pytest.mark.asyncio
    async def test_delete_variable(self, var_repo: VariableRepository) -> None:
        """Test deleting a variable."""
        await var_repo.set("delete_key", "delete_value")

        deleted = await var_repo.delete("delete_key")
        assert deleted is True

        var = await var_repo.get("delete_key")
        assert var is None

    @pytest.mark.asyncio
    async def test_get_all(self, var_repo: VariableRepository) -> None:
        """Test getting all variables."""
        await var_repo.set("var_a", "value_a")
        await var_repo.set("var_b", "value_b")

        all_vars = await var_repo.get_all()
        assert len(all_vars) == 2
        assert any(v.name == "var_a" for v in all_vars)
        assert any(v.name == "var_b" for v in all_vars)
