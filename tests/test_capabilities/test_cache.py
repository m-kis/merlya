"""Tests for capabilities cache."""

from datetime import UTC, datetime, timedelta

import pytest

from merlya.capabilities.cache import CapabilityCache
from merlya.capabilities.models import (
    HostCapabilities,
    LocalCapabilities,
    SSHCapability,
    ToolCapability,
    ToolName,
)


@pytest.fixture
def cache() -> CapabilityCache:
    """Create a fresh cache for each test."""
    return CapabilityCache(default_ttl=3600)


@pytest.fixture
def host_caps() -> HostCapabilities:
    """Create sample host capabilities."""
    return HostCapabilities(
        host_name="web-01",
        ssh=SSHCapability(available=True),
        tools=[
            ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
        ],
        web_access=True,
        ttl_seconds=3600,
    )


@pytest.fixture
def local_caps() -> LocalCapabilities:
    """Create sample local capabilities."""
    return LocalCapabilities(
        tools=[
            ToolCapability(name=ToolName.GIT, installed=True),
        ],
        web_access=True,
        ttl_seconds=3600,
    )


class TestCapabilityCache:
    """Tests for CapabilityCache."""

    async def test_get_host_returns_none_when_empty(self, cache: CapabilityCache) -> None:
        """Test get_host returns None when cache is empty."""
        result = await cache.get_host("unknown-host")
        assert result is None

    async def test_set_and_get_host(
        self, cache: CapabilityCache, host_caps: HostCapabilities
    ) -> None:
        """Test setting and getting host capabilities."""
        await cache.set_host(host_caps)
        result = await cache.get_host("web-01")
        assert result is not None
        assert result.host_name == "web-01"
        assert result.ssh.available is True

    async def test_get_host_returns_none_when_expired(self, cache: CapabilityCache) -> None:
        """Test get_host returns None when cached item is expired."""
        expired_caps = HostCapabilities(
            host_name="old-host",
            cached_at=datetime.now(UTC) - timedelta(hours=25),
            ttl_seconds=86400,
        )
        await cache.set_host(expired_caps)

        # Force the cached_at to be in the past
        cache._host_cache["old-host"].cached_at = datetime.now(UTC) - timedelta(hours=25)

        result = await cache.get_host("old-host")
        assert result is None

    async def test_get_local_returns_none_when_empty(self, cache: CapabilityCache) -> None:
        """Test get_local returns None when cache is empty."""
        result = await cache.get_local()
        assert result is None

    async def test_set_and_get_local(
        self, cache: CapabilityCache, local_caps: LocalCapabilities
    ) -> None:
        """Test setting and getting local capabilities."""
        await cache.set_local(local_caps)
        result = await cache.get_local()
        assert result is not None
        assert result.web_access is True

    async def test_invalidate_host(
        self, cache: CapabilityCache, host_caps: HostCapabilities
    ) -> None:
        """Test invalidating a host from cache."""
        await cache.set_host(host_caps)
        assert await cache.get_host("web-01") is not None

        await cache.invalidate_host("web-01")
        assert await cache.get_host("web-01") is None

    async def test_invalidate_all(
        self,
        cache: CapabilityCache,
        host_caps: HostCapabilities,
        local_caps: LocalCapabilities,
    ) -> None:
        """Test invalidating all cached items."""
        await cache.set_host(host_caps)
        await cache.set_local(local_caps)

        await cache.invalidate_all()

        assert await cache.get_host("web-01") is None
        assert await cache.get_local() is None

    async def test_cleanup_expired(self, cache: CapabilityCache) -> None:
        """Test cleanup of expired entries."""
        # Add fresh and expired entries
        fresh = HostCapabilities(
            host_name="fresh-host",
            ttl_seconds=3600,
        )
        await cache.set_host(fresh)

        expired = HostCapabilities(
            host_name="expired-host",
            ttl_seconds=1,  # 1 second TTL
        )
        await cache.set_host(expired)

        # Force the expired entry to be old
        cache._host_cache["expired-host"].cached_at = datetime.now(UTC) - timedelta(seconds=10)

        removed = await cache.cleanup_expired()
        assert removed == 1
        assert await cache.get_host("fresh-host") is not None
        assert await cache.get_host("expired-host") is None

    async def test_size_property(self, cache: CapabilityCache, host_caps: HostCapabilities) -> None:
        """Test size property returns correct count."""
        assert cache.size == 0

        await cache.set_host(host_caps)
        assert cache.size == 1

        host2 = HostCapabilities(host_name="web-02")
        await cache.set_host(host2)
        assert cache.size == 2
