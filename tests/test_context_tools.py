"""
Tests for Context Tools.

Tests HostsSummary, HostDetails, GroupSummary and async functions.
"""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.tools.context.tools import (
    GroupSummary,
    HostDetails,
    HostsSummary,
    get_host_details,
    get_infrastructure_context,
    list_groups,
    list_hosts_summary,
)


class TestHostsSummary:
    """Tests for HostsSummary dataclass."""

    def test_basic_summary(self):
        """Test basic summary creation."""
        summary = HostsSummary(
            total_count=100,
            healthy_count=90,
            unhealthy_count=5,
            unknown_count=5,
        )

        assert summary.total_count == 100
        assert summary.healthy_count == 90
        assert summary.unhealthy_count == 5
        assert summary.unknown_count == 5
        assert summary.by_tag == {}
        assert summary.sample_hosts == []

    def test_summary_with_tags(self):
        """Test summary with tag counts."""
        summary = HostsSummary(
            total_count=50,
            healthy_count=45,
            unhealthy_count=3,
            unknown_count=2,
            by_tag={"production": 30, "staging": 10, "development": 10},
            by_status={"healthy": 45, "unhealthy": 3, "unknown": 2},
        )

        assert len(summary.by_tag) == 3
        assert summary.by_tag["production"] == 30

    def test_to_text_basic(self):
        """Test basic text output."""
        summary = HostsSummary(
            total_count=10,
            healthy_count=8,
            unhealthy_count=1,
            unknown_count=1,
        )

        text = summary.to_text()

        assert "📊 Inventory: 10 hosts" in text
        assert "✅ Healthy: 8" in text
        assert "❌ Unhealthy: 1" in text
        assert "❓ Unknown: 1" in text

    def test_to_text_with_tags(self):
        """Test text output with tags."""
        summary = HostsSummary(
            total_count=10,
            healthy_count=10,
            unhealthy_count=0,
            unknown_count=0,
            by_tag={"web": 5, "db": 3, "cache": 2},
        )

        text = summary.to_text()

        assert "🏷️ Tags:" in text
        assert "cache:2" in text
        assert "db:3" in text
        assert "web:5" in text

    def test_to_text_with_samples(self):
        """Test text output with sample hosts."""
        summary = HostsSummary(
            total_count=10,
            healthy_count=10,
            unhealthy_count=0,
            unknown_count=0,
            sample_hosts=["web-01", "web-02", "db-01"],
        )

        text = summary.to_text()

        assert "📋 Sample:" in text
        assert "web-01" in text

    def test_to_text_truncates_samples(self):
        """Test that sample hosts are truncated to 5."""
        summary = HostsSummary(
            total_count=20,
            healthy_count=20,
            unhealthy_count=0,
            unknown_count=0,
            sample_hosts=["h1", "h2", "h3", "h4", "h5", "h6", "h7"],
        )

        text = summary.to_text()

        # Should only show first 5
        assert "h6" not in text
        assert "h7" not in text


class TestHostDetails:
    """Tests for HostDetails dataclass."""

    def test_basic_details(self):
        """Test basic host details."""
        details = HostDetails(
            name="web-01",
            hostname="192.168.1.10",
            port=22,
            username="admin",
            jump_host=None,
            tags=["production", "web"],
            health_status="healthy",
            last_seen="2024-01-15T10:30:00",
            os_info={"name": "Ubuntu", "version": "22.04"},
            metadata={},
        )

        assert details.name == "web-01"
        assert details.port == 22
        assert len(details.tags) == 2

    def test_to_text_basic(self):
        """Test basic text output."""
        details = HostDetails(
            name="db-01",
            hostname="10.0.0.5",
            port=22,
            username=None,
            jump_host=None,
            tags=[],
            health_status="healthy",
            last_seen=None,
            os_info=None,
            metadata={},
        )

        text = details.to_text()

        assert "🖥️ Host: db-01" in text
        assert "Address: 10.0.0.5:22" in text
        assert "Status: healthy" in text

    def test_to_text_with_username(self):
        """Test text output with username."""
        details = HostDetails(
            name="web-01",
            hostname="host.example.com",
            port=2222,
            username="deploy",
            jump_host=None,
            tags=[],
            health_status="healthy",
            last_seen=None,
            os_info=None,
            metadata={},
        )

        text = details.to_text()

        assert "User: deploy" in text

    def test_to_text_with_jump_host(self):
        """Test text output with jump host."""
        details = HostDetails(
            name="internal-01",
            hostname="192.168.100.10",
            port=22,
            username="admin",
            jump_host="bastion.example.com",
            tags=[],
            health_status="healthy",
            last_seen=None,
            os_info=None,
            metadata={},
        )

        text = details.to_text()

        assert "Via: bastion.example.com" in text

    def test_to_text_with_tags(self):
        """Test text output with tags."""
        details = HostDetails(
            name="web-01",
            hostname="host.example.com",
            port=22,
            username=None,
            jump_host=None,
            tags=["production", "web", "critical"],
            health_status="healthy",
            last_seen=None,
            os_info=None,
            metadata={},
        )

        text = details.to_text()

        assert "Tags: production, web, critical" in text

    def test_to_text_with_os_info(self):
        """Test text output with OS info."""
        details = HostDetails(
            name="web-01",
            hostname="host.example.com",
            port=22,
            username=None,
            jump_host=None,
            tags=[],
            health_status="healthy",
            last_seen=None,
            os_info={"name": "Debian", "version": "12"},
            metadata={},
        )

        text = details.to_text()

        assert "OS: Debian 12" in text

    def test_to_text_with_last_seen(self):
        """Test text output with last seen time."""
        details = HostDetails(
            name="web-01",
            hostname="host.example.com",
            port=22,
            username=None,
            jump_host=None,
            tags=[],
            health_status="unknown",
            last_seen="2024-01-15T10:30:00Z",
            os_info=None,
            metadata={},
        )

        text = details.to_text()

        assert "Last seen:" in text
        assert "2024-01-15" in text


class TestGroupSummary:
    """Tests for GroupSummary dataclass."""

    def test_basic_group(self):
        """Test basic group summary."""
        group = GroupSummary(
            name="production",
            host_count=10,
            healthy_count=9,
        )

        assert group.name == "production"
        assert group.host_count == 10
        assert group.healthy_count == 9

    def test_to_text(self):
        """Test text output."""
        group = GroupSummary(
            name="web",
            host_count=5,
            healthy_count=4,
            sample_hosts=["web-01", "web-02", "web-03"],
        )

        text = group.to_text()

        assert "📁 web:" in text
        assert "5 hosts" in text
        assert "80%" in text  # 4/5 = 80%
        assert "web-01" in text

    def test_to_text_zero_hosts(self):
        """Test text output with zero hosts (avoid division by zero)."""
        group = GroupSummary(
            name="empty",
            host_count=0,
            healthy_count=0,
        )

        text = group.to_text()

        assert "0 hosts" in text
        # Should not crash on division by zero


class TestListHostsSummary:
    """Tests for list_hosts_summary function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        ctx = MagicMock()
        ctx.db = MagicMock()
        return ctx

    @pytest.fixture
    def mock_hosts(self):
        """Create mock host objects."""
        hosts = []
        for i in range(5):
            host = MagicMock()
            host.name = f"web-{i + 1:02d}"
            host.health_status = "healthy" if i < 4 else "unhealthy"
            host.tags = ["production", "web"] if i < 3 else ["staging"]
            hosts.append(host)
        return hosts

    @pytest.mark.asyncio
    async def test_list_hosts_summary_basic(self, mock_context, mock_hosts):
        """Test basic host summary listing."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=mock_hosts)

            summary = await list_hosts_summary(mock_context)

            assert summary.total_count == 5
            assert summary.healthy_count == 4
            assert summary.unhealthy_count == 1
            assert len(summary.sample_hosts) == 5

    @pytest.mark.asyncio
    async def test_list_hosts_summary_with_tag_filter(self, mock_context, mock_hosts):
        """Test host summary with tag filter."""
        production_hosts = [h for h in mock_hosts if "production" in h.tags]

        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_by_tag = AsyncMock(return_value=production_hosts)

            summary = await list_hosts_summary(mock_context, tag="production")

            mock_repo.get_by_tag.assert_called_once_with("production")
            assert summary.total_count == 3

    @pytest.mark.asyncio
    async def test_list_hosts_summary_with_status_filter(self, mock_context, mock_hosts):
        """Test host summary with status filter."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=mock_hosts)

            summary = await list_hosts_summary(mock_context, status="healthy")

            # Should filter to only healthy hosts
            assert summary.total_count == 4

    @pytest.mark.asyncio
    async def test_list_hosts_summary_empty(self, mock_context):
        """Test host summary with no hosts."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=[])

            summary = await list_hosts_summary(mock_context)

            assert summary.total_count == 0
            assert summary.healthy_count == 0


class TestGetHostDetails:
    """Tests for get_host_details function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        ctx = MagicMock()
        ctx.db = MagicMock()
        return ctx

    @pytest.fixture
    def mock_host(self):
        """Create a mock host object."""
        from datetime import datetime

        host = MagicMock()
        host.name = "web-01"
        host.hostname = "192.168.1.10"
        host.port = 22
        host.username = "admin"
        host.jump_host = None
        host.tags = ["production", "web"]
        host.health_status = "healthy"
        host.last_seen = datetime.now(UTC)
        host.os_info = MagicMock()
        host.os_info.model_dump.return_value = {"name": "Ubuntu", "version": "22.04"}
        host.metadata = {}
        return host

    @pytest.mark.asyncio
    async def test_get_host_details_found(self, mock_context, mock_host):
        """Test getting details for existing host."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_by_name = AsyncMock(return_value=mock_host)

            details = await get_host_details(mock_context, "web-01")

            assert details is not None
            assert details.name == "web-01"
            assert details.hostname == "192.168.1.10"

    @pytest.mark.asyncio
    async def test_get_host_details_not_found_by_name(self, mock_context, mock_host):
        """Test fallback to ID lookup when name not found."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_by_name = AsyncMock(return_value=None)
            mock_repo.get_by_id = AsyncMock(return_value=mock_host)

            details = await get_host_details(mock_context, "abc123")

            mock_repo.get_by_id.assert_called_once_with("abc123")
            assert details is not None

    @pytest.mark.asyncio
    async def test_get_host_details_not_found(self, mock_context):
        """Test host not found."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_by_name = AsyncMock(return_value=None)
            mock_repo.get_by_id = AsyncMock(return_value=None)

            details = await get_host_details(mock_context, "nonexistent")

            assert details is None

    @pytest.mark.asyncio
    async def test_get_host_details_no_os_info(self, mock_context, mock_host):
        """Test host without OS info."""
        mock_host.os_info = None

        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_by_name = AsyncMock(return_value=mock_host)

            details = await get_host_details(mock_context, "web-01")

            assert details is not None
            assert details.os_info is None


class TestListGroups:
    """Tests for list_groups function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        ctx = MagicMock()
        ctx.db = MagicMock()
        return ctx

    @pytest.fixture
    def mock_hosts_with_tags(self):
        """Create mock hosts with various tags."""
        hosts = []
        for i in range(10):
            host = MagicMock()
            host.name = f"host-{i + 1:02d}"
            host.health_status = "healthy" if i < 8 else "unhealthy"
            if i < 5:
                host.tags = ["production", "web"]
            elif i < 8:
                host.tags = ["production", "db"]
            else:
                host.tags = ["staging"]
            hosts.append(host)
        return hosts

    @pytest.mark.asyncio
    async def test_list_groups_basic(self, mock_context, mock_hosts_with_tags):
        """Test basic group listing."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=mock_hosts_with_tags)

            groups = await list_groups(mock_context)

            # Should have production, web, db, staging groups
            assert len(groups) >= 3
            group_names = [g.name for g in groups]
            assert "production" in group_names

    @pytest.mark.asyncio
    async def test_list_groups_sorted_by_count(self, mock_context, mock_hosts_with_tags):
        """Test groups are sorted by host count (descending)."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=mock_hosts_with_tags)

            groups = await list_groups(mock_context)

            # Should be sorted by count descending
            for i in range(len(groups) - 1):
                assert groups[i].host_count >= groups[i + 1].host_count

    @pytest.mark.asyncio
    async def test_list_groups_empty(self, mock_context):
        """Test with no hosts."""
        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=[])

            groups = await list_groups(mock_context)

            assert groups == []


class TestGetInfrastructureContext:
    """Tests for get_infrastructure_context function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        ctx = MagicMock()
        ctx.db = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_get_context_basic(self, mock_context):
        """Test basic infrastructure context."""
        mock_host = MagicMock()
        mock_host.name = "web-01"
        mock_host.health_status = "healthy"
        mock_host.tags = ["production"]

        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=[mock_host])

            context = await get_infrastructure_context(mock_context)

            assert "📊 Inventory:" in context
            assert "1 hosts" in context

    @pytest.mark.asyncio
    async def test_get_context_includes_groups(self, mock_context):
        """Test context includes groups by default."""
        mock_host = MagicMock()
        mock_host.name = "web-01"
        mock_host.health_status = "healthy"
        mock_host.tags = ["production"]

        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=[mock_host])

            context = await get_infrastructure_context(mock_context, include_groups=True)

            assert "📁 Groups:" in context

    @pytest.mark.asyncio
    async def test_get_context_without_groups(self, mock_context):
        """Test context without groups."""
        mock_host = MagicMock()
        mock_host.name = "web-01"
        mock_host.health_status = "healthy"
        mock_host.tags = []

        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=[mock_host])

            context = await get_infrastructure_context(mock_context, include_groups=False)

            assert "📁 Groups:" not in context

    @pytest.mark.asyncio
    async def test_get_context_limits_groups(self, mock_context):
        """Test that groups are limited by max_groups."""
        hosts = []
        for i in range(10):
            host = MagicMock()
            host.name = f"host-{i}"
            host.health_status = "healthy"
            host.tags = [f"tag-{i}"]  # Each host has unique tag
            hosts.append(host)

        with patch("merlya.persistence.repositories.HostRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.get_all = AsyncMock(return_value=hosts)

            context = await get_infrastructure_context(mock_context, max_groups=3)

            # Should mention "and X more groups"
            assert "more groups" in context
