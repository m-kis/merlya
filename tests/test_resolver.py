"""Tests for host resolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.hosts.resolver import (
    HostNotFoundError,
    HostResolver,
    InvalidHostQueryError,
)
from merlya.persistence.models import Host


class TestHostResolverValidation:
    """Tests for query validation."""

    @pytest.fixture
    def resolver(self) -> HostResolver:
        """Create resolver with mock repo."""
        mock_repo = MagicMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.get_all = AsyncMock(return_value=[])
        return HostResolver(mock_repo)

    def test_validate_empty_query(self, resolver: HostResolver) -> None:
        """Test empty query raises error."""
        with pytest.raises(InvalidHostQueryError, match="cannot be empty"):
            resolver._validate_query("")

        with pytest.raises(InvalidHostQueryError, match="cannot be empty"):
            resolver._validate_query("   ")

    def test_validate_null_bytes(self, resolver: HostResolver) -> None:
        """Test null bytes in query raises error."""
        with pytest.raises(InvalidHostQueryError, match="null bytes"):
            resolver._validate_query("host\x00name")

    def test_validate_too_long(self, resolver: HostResolver) -> None:
        """Test too long query raises error."""
        long_query = "a" * 300
        with pytest.raises(InvalidHostQueryError, match="exceeds maximum"):
            resolver._validate_query(long_query)

    def test_validate_ipv4(self, resolver: HostResolver) -> None:
        """Test valid IPv4 addresses pass."""
        assert resolver._validate_query("192.168.1.1") == "192.168.1.1"
        assert resolver._validate_query("10.0.0.1") == "10.0.0.1"
        assert resolver._validate_query("255.255.255.255") == "255.255.255.255"

    def test_validate_hostname(self, resolver: HostResolver) -> None:
        """Test valid hostnames pass."""
        assert resolver._validate_query("server") == "server"
        assert resolver._validate_query("web-01") == "web-01"
        assert resolver._validate_query("db_prod") == "db_prod"
        assert resolver._validate_query("host.example.com") == "host.example.com"

    def test_validate_strips_whitespace(self, resolver: HostResolver) -> None:
        """Test whitespace is stripped."""
        assert resolver._validate_query("  server  ") == "server"


class TestHostResolver:
    """Tests for host resolution."""

    @pytest.fixture
    def mock_repo(self) -> MagicMock:
        """Create mock repository."""
        repo = MagicMock()
        repo.get_by_name = AsyncMock(return_value=None)
        repo.get_all = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def resolver(self, mock_repo: MagicMock) -> HostResolver:
        """Create resolver with mock repo."""
        return HostResolver(mock_repo, local_timeout=0.1, dns_timeout=0.1)

    @pytest.mark.asyncio
    async def test_resolve_from_inventory(
        self, resolver: HostResolver, mock_repo: MagicMock
    ) -> None:
        """Test resolution from inventory."""
        host = Host(
            name="my-server",
            hostname="192.168.1.100",
            metadata={"ip": "192.168.1.100"},
        )
        mock_repo.get_by_name.return_value = host

        result = await resolver.resolve("my-server")

        assert result.query == "my-server"
        assert result.hostname == "192.168.1.100"
        assert result.ip == "192.168.1.100"
        assert result.source == "inventory"
        assert result.host_id == host.id

    @pytest.mark.asyncio
    async def test_resolve_localhost(self, resolver: HostResolver) -> None:
        """Test resolution of localhost."""
        result = await resolver.resolve("localhost")

        assert result.query == "localhost"
        assert result.ip == "127.0.0.1"
        assert result.source == "local"

    @pytest.mark.asyncio
    async def test_resolve_not_found(self, resolver: HostResolver) -> None:
        """Test resolution failure raises error."""
        with pytest.raises(HostNotFoundError) as exc_info:
            await resolver.resolve("nonexistent.invalid.local")

        assert "could not be resolved" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resolve_suggestions(self, resolver: HostResolver, mock_repo: MagicMock) -> None:
        """Test suggestions are provided on failure."""
        mock_repo.get_all.return_value = [
            Host(name="web-server", hostname="192.168.1.1"),
            Host(name="web-backup", hostname="192.168.1.2"),
            Host(name="db-server", hostname="192.168.1.3"),
        ]

        with pytest.raises(HostNotFoundError) as exc_info:
            await resolver.resolve("web")

        assert "web-server" in exc_info.value.suggestions
        assert "web-backup" in exc_info.value.suggestions
