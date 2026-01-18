"""Tests for HostTargetResolver - centralized local/remote routing."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.hosts.target_resolver import (
    HostTargetResolver,
    ResolvedTarget,
    TargetType,
    is_local_target,
)
from merlya.persistence.models import Host


class TestIsLocalTarget:
    """Test the is_local_target utility function."""

    def test_local_keyword(self):
        """Test 'local' is recognized as local."""
        assert is_local_target("local") is True

    def test_localhost(self):
        """Test 'localhost' is recognized as local."""
        assert is_local_target("localhost") is True

    def test_localhost_uppercase(self):
        """Test case insensitivity for localhost."""
        assert is_local_target("LOCALHOST") is True
        assert is_local_target("LocalHost") is True

    def test_ipv4_loopback(self):
        """Test 127.0.0.1 is recognized as local."""
        assert is_local_target("127.0.0.1") is True

    def test_ipv6_loopback(self):
        """Test ::1 is recognized as local."""
        assert is_local_target("::1") is True

    def test_remote_hostname(self):
        """Test remote hostname is not local."""
        assert is_local_target("webserver") is False
        assert is_local_target("pine64") is False

    def test_remote_ip(self):
        """Test remote IP is not local."""
        assert is_local_target("192.168.1.7") is False
        assert is_local_target("10.0.0.1") is False

    def test_empty_string(self):
        """Test empty string is not local."""
        assert is_local_target("") is False

    def test_whitespace(self):
        """Test whitespace-only is not local."""
        assert is_local_target("   ") is False


class TestHostTargetResolverStatic:
    """Test static methods of HostTargetResolver."""

    def test_looks_like_ip_valid_ipv4(self):
        """Test valid IPv4 addresses."""
        assert HostTargetResolver.looks_like_ip("192.168.1.1") is True
        assert HostTargetResolver.looks_like_ip("10.0.0.1") is True
        assert HostTargetResolver.looks_like_ip("172.16.0.1") is True
        assert HostTargetResolver.looks_like_ip("255.255.255.255") is True

    def test_looks_like_ip_invalid(self):
        """Test invalid IP addresses."""
        assert HostTargetResolver.looks_like_ip("192.168.1.256") is False
        assert HostTargetResolver.looks_like_ip("not-an-ip") is False
        assert HostTargetResolver.looks_like_ip("192.168.1") is False

    def test_looks_like_hostname_valid(self):
        """Test valid hostnames."""
        assert HostTargetResolver.looks_like_hostname("webserver") is True
        assert HostTargetResolver.looks_like_hostname("web-server") is True
        assert HostTargetResolver.looks_like_hostname("web.example.com") is True
        assert HostTargetResolver.looks_like_hostname("server01") is True

    def test_looks_like_hostname_invalid(self):
        """Test invalid hostnames."""
        assert HostTargetResolver.looks_like_hostname("") is False
        assert HostTargetResolver.looks_like_hostname("@secret") is False
        assert HostTargetResolver.looks_like_hostname("-invalid") is False


class TestHostTargetResolverResolve:
    """Test the resolve method of HostTargetResolver."""

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock SharedContext."""
        ctx = MagicMock()
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(return_value=None)
        ctx.hosts.get_by_hostname = AsyncMock(return_value=None)
        ctx.hosts.get_all = AsyncMock(return_value=[])
        ctx.session = MagicMock()
        ctx.session.last_remote_target = None
        return ctx

    @pytest.mark.asyncio
    async def test_resolve_local_alias(self, mock_ctx):
        """Test resolution of local aliases."""
        resolver = HostTargetResolver(mock_ctx)

        for alias in ["local", "localhost", "127.0.0.1", "::1"]:
            target = await resolver.resolve(alias)
            assert target.target_type == TargetType.LOCAL
            assert target.is_local is True
            assert target.source == "local_alias"

    @pytest.mark.asyncio
    async def test_resolve_inventory_by_name(self, mock_ctx):
        """Test resolution from inventory by name."""
        mock_host = Host(name="pine64", hostname="192.168.1.7", port=22)
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=mock_host)

        resolver = HostTargetResolver(mock_ctx)
        target = await resolver.resolve("pine64")

        assert target.target_type == TargetType.REMOTE
        assert target.is_remote is True
        assert target.hostname == "192.168.1.7"
        assert target.host_entry == mock_host
        assert target.source == "inventory"

    @pytest.mark.asyncio
    async def test_resolve_inventory_by_hostname(self, mock_ctx):
        """Test resolution from inventory by hostname/IP."""
        mock_host = Host(name="pine64", hostname="192.168.1.7", port=22)
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=None)
        mock_ctx.hosts.get_by_hostname = AsyncMock(return_value=mock_host)

        resolver = HostTargetResolver(mock_ctx)
        target = await resolver.resolve("192.168.1.7")

        assert target.target_type == TargetType.REMOTE
        assert target.hostname == "192.168.1.7"
        assert target.source == "inventory"

    @pytest.mark.asyncio
    async def test_resolve_direct_ip(self, mock_ctx):
        """Test resolution of direct IP address (via DNS first, then direct fallback)."""
        # DNS resolution is attempted first for IPs, so mock it to succeed
        with patch("merlya.hosts.target_resolver.socket.gethostbyname", return_value="10.0.0.50"):
            resolver = HostTargetResolver(mock_ctx)
            target = await resolver.resolve("10.0.0.50")

            assert target.target_type == TargetType.REMOTE
            assert target.hostname == "10.0.0.50"
            # Note: IPs go through DNS first, so source is "dns" if DNS succeeds
            assert target.source == "dns"
            assert target.host_entry is None

    @pytest.mark.asyncio
    async def test_resolve_direct_ip_dns_fails(self, mock_ctx):
        """Test resolution of direct IP when DNS fails - uses ip_direct."""
        with patch(
            "merlya.hosts.target_resolver.socket.gethostbyname",
            side_effect=socket.gaierror("DNS failed"),
        ):
            resolver = HostTargetResolver(mock_ctx)
            target = await resolver.resolve("10.0.0.50")

            assert target.target_type == TargetType.REMOTE
            assert target.hostname == "10.0.0.50"
            assert target.source == "ip_direct"
            assert target.host_entry is None

    @pytest.mark.asyncio
    async def test_resolve_strips_at_prefix(self, mock_ctx):
        """Test that @ prefix is stripped from host."""
        mock_host = Host(name="pine64", hostname="192.168.1.7", port=22)
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=mock_host)

        resolver = HostTargetResolver(mock_ctx)
        target = await resolver.resolve("@pine64")

        assert target.target_type == TargetType.REMOTE
        assert target.hostname == "192.168.1.7"

    @pytest.mark.asyncio
    async def test_resolve_empty_host(self, mock_ctx):
        """Test resolution of empty host string."""
        resolver = HostTargetResolver(mock_ctx)
        target = await resolver.resolve("")

        assert target.target_type == TargetType.UNKNOWN
        assert target.source == "empty"

    @pytest.mark.asyncio
    async def test_resolve_unknown_host(self, mock_ctx):
        """Test resolution of unknown host without DNS."""
        with patch(
            "merlya.hosts.target_resolver.socket.gethostbyname",
            side_effect=socket.gaierror("DNS failed"),
        ):
            resolver = HostTargetResolver(mock_ctx)
            target = await resolver.resolve("unknown-host-xyz")

            assert target.target_type == TargetType.UNKNOWN
            assert target.source == "unknown"

    @pytest.mark.asyncio
    async def test_resolve_dns_fallback(self, mock_ctx):
        """Test DNS resolution fallback."""
        with patch(
            "merlya.hosts.target_resolver.socket.gethostbyname", return_value="93.184.216.34"
        ):
            resolver = HostTargetResolver(mock_ctx)
            target = await resolver.resolve("example.com")

            assert target.target_type == TargetType.REMOTE
            assert target.hostname == "example.com"
            assert target.source == "dns"

    @pytest.mark.asyncio
    async def test_resolve_session_fallback(self, mock_ctx):
        """Test session context fallback for follow-up questions."""
        mock_host = Host(name="pine64", hostname="192.168.1.7", port=22)
        mock_ctx.hosts.get_by_name = AsyncMock(side_effect=[None, mock_host])
        mock_ctx.session.last_remote_target = "pine64"

        with patch(
            "merlya.hosts.target_resolver.socket.gethostbyname",
            side_effect=socket.gaierror("DNS failed"),
        ):
            resolver = HostTargetResolver(mock_ctx)
            target = await resolver.resolve("some-unknown-thing")

            # Should fall back to last_remote_target
            assert target.target_type == TargetType.REMOTE
            assert target.hostname == "192.168.1.7"

    @pytest.mark.asyncio
    async def test_update_session_target(self, mock_ctx):
        """Test updating session target after resolution."""
        mock_host = Host(name="pine64", hostname="192.168.1.7", port=22)
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=mock_host)

        resolver = HostTargetResolver(mock_ctx)
        target = await resolver.resolve("pine64")

        resolver.update_session_target(target)
        assert mock_ctx.session.last_remote_target == "pine64"

    @pytest.mark.asyncio
    async def test_resolve_or_fail_success(self, mock_ctx):
        """Test resolve_or_fail with successful resolution."""
        mock_host = Host(name="pine64", hostname="192.168.1.7", port=22)
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=mock_host)

        resolver = HostTargetResolver(mock_ctx)
        target = await resolver.resolve_or_fail("pine64")

        assert target.target_type == TargetType.REMOTE

    @pytest.mark.asyncio
    async def test_resolve_or_fail_raises(self, mock_ctx):
        """Test resolve_or_fail raises on unknown host."""
        with patch(
            "merlya.hosts.target_resolver.socket.gethostbyname",
            side_effect=socket.gaierror("DNS failed"),
        ):
            resolver = HostTargetResolver(mock_ctx)

            with pytest.raises(ValueError) as exc_info:
                await resolver.resolve_or_fail("unknown-host-xyz")

            assert "not found in inventory" in str(exc_info.value)


class TestResolvedTarget:
    """Test the ResolvedTarget dataclass."""

    def test_is_local_property(self):
        """Test is_local property."""
        target = ResolvedTarget(
            original_query="localhost",
            target_type=TargetType.LOCAL,
            hostname="local",
            host_entry=None,
            source="local_alias",
        )
        assert target.is_local is True
        assert target.is_remote is False

    def test_is_remote_property(self):
        """Test is_remote property."""
        target = ResolvedTarget(
            original_query="pine64",
            target_type=TargetType.REMOTE,
            hostname="192.168.1.7",
            host_entry=None,
            source="inventory",
        )
        assert target.is_local is False
        assert target.is_remote is True


class TestFindSimilarHosts:
    """Test the similar hosts suggestion feature."""

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock SharedContext with hosts."""
        ctx = MagicMock()
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(return_value=None)
        ctx.hosts.get_by_hostname = AsyncMock(return_value=None)
        ctx.hosts.get_all = AsyncMock(
            return_value=[
                Host(name="pine64", hostname="192.168.1.7", port=22),
                Host(name="pinebook", hostname="192.168.1.8", port=22),
                Host(name="webserver", hostname="192.168.1.10", port=22),
            ]
        )
        ctx.session = MagicMock()
        ctx.session.last_remote_target = None
        return ctx

    @pytest.mark.asyncio
    async def test_find_similar_by_substring(self, mock_ctx):
        """Test finding similar hosts by substring match."""
        resolver = HostTargetResolver(mock_ctx)
        similar = await resolver.find_similar_hosts("pine")

        assert "pine64" in similar
        assert "pinebook" in similar
        assert "webserver" not in similar

    @pytest.mark.asyncio
    async def test_find_similar_limits_results(self, mock_ctx):
        """Test that similar hosts are limited to 5."""
        mock_ctx.hosts.get_all = AsyncMock(
            return_value=[
                Host(name=f"server{i}", hostname=f"192.168.1.{i}", port=22) for i in range(10)
            ]
        )
        resolver = HostTargetResolver(mock_ctx)
        similar = await resolver.find_similar_hosts("server")

        assert len(similar) <= 5
