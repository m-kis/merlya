"""Tests for /scan command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.commands.handlers.system import cmd_scan
from merlya.persistence.models import Host


class TestScanCommand:
    """Tests for /scan command."""

    @pytest.fixture
    def mock_host(self) -> Host:
        """Create a mock host."""
        return Host(
            name="testserver",
            hostname="192.168.1.100",
            port=22,
            username="admin",
        )

    @pytest.fixture
    def mock_context(self, mock_host: Host) -> MagicMock:
        """Create a mock context."""
        ctx = MagicMock()
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(return_value=mock_host)
        ctx.ui = MagicMock()
        ctx.ui.info = MagicMock()
        ctx.ui.muted = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_scan_no_args(self, mock_context: MagicMock) -> None:
        """Test scan with no arguments shows help."""
        result = await cmd_scan(mock_context, [])

        assert not result.success
        assert "Usage:" in result.message
        assert result.show_help

    @pytest.mark.asyncio
    async def test_scan_host_not_found(self, mock_context: MagicMock) -> None:
        """Test scan with unknown host."""
        mock_context.hosts.get_by_name = AsyncMock(return_value=None)

        result = await cmd_scan(mock_context, ["unknown-host"])

        assert not result.success
        assert "not found" in result.message
        assert "/hosts add" in result.message

    @pytest.mark.asyncio
    async def test_scan_strips_at_prefix(self, mock_context: MagicMock) -> None:
        """Test scan handles @hostname format."""
        await cmd_scan(mock_context, ["@testserver"])

        mock_context.hosts.get_by_name.assert_called_with("testserver")


class TestScanValidation:
    """Tests for scan input validation."""

    @pytest.fixture
    def mock_context(self) -> MagicMock:
        """Create a mock context."""
        ctx = MagicMock()
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(return_value=None)
        ctx.ui = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_empty_hostname_rejected(self, mock_context: MagicMock) -> None:
        """Test empty hostname is rejected."""
        result = await cmd_scan(mock_context, [""])

        # Empty string stripped becomes empty, host not found
        assert not result.success

    @pytest.mark.asyncio
    async def test_at_only_hostname(self, mock_context: MagicMock) -> None:
        """Test @ only is handled."""
        result = await cmd_scan(mock_context, ["@"])

        # @ stripped becomes empty
        assert not result.success
