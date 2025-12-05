"""Tests for /scan command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.commands.handlers import cmd_scan
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

    @pytest.mark.asyncio
    async def test_scan_full_by_default(
        self, mock_context: MagicMock, mock_host: Host  # noqa: ARG002
    ) -> None:
        """Test full scan is default."""
        with patch("merlya.tools.system.get_system_info") as mock_sys, \
             patch("merlya.tools.system.check_memory") as mock_mem, \
             patch("merlya.tools.system.check_cpu") as mock_cpu, \
             patch("merlya.tools.system.check_disk_usage") as mock_disk, \
             patch("merlya.tools.security.check_open_ports") as mock_ports, \
             patch("merlya.tools.security.check_security_config") as mock_sec, \
             patch("merlya.tools.security.check_users") as mock_users:

            # Setup mocks
            mock_sys.return_value = MagicMock(success=True, data={"os": "Ubuntu"})
            mock_mem.return_value = MagicMock(success=True, data={"use_percent": 50})
            mock_cpu.return_value = MagicMock(success=True, data={"use_percent": 30})
            mock_disk.return_value = MagicMock(success=True, data={"use_percent": 40})
            mock_ports.return_value = MagicMock(success=True, data=[])
            mock_sec.return_value = MagicMock(success=True, data={"issues": []})
            mock_users.return_value = MagicMock(
                success=True, data={"sudo_users": [], "shell_users": []}
            )

            result = await cmd_scan(mock_context, ["testserver"])

            assert result.success
            # Both system and security should be called
            mock_sys.assert_called_once()
            mock_ports.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_system_only(self, mock_context: MagicMock) -> None:
        """Test --system flag scans only system info."""
        with patch("merlya.tools.system.get_system_info") as mock_sys, \
             patch("merlya.tools.system.check_memory") as mock_mem, \
             patch("merlya.tools.system.check_cpu") as mock_cpu, \
             patch("merlya.tools.system.check_disk_usage") as mock_disk:

            mock_sys.return_value = MagicMock(success=True, data={})
            mock_mem.return_value = MagicMock(success=True, data={})
            mock_cpu.return_value = MagicMock(success=True, data={})
            mock_disk.return_value = MagicMock(success=True, data={})

            result = await cmd_scan(mock_context, ["testserver", "--system"])

            assert result.success
            mock_sys.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_security_only(self, mock_context: MagicMock) -> None:
        """Test --security flag scans only security."""
        with patch("merlya.tools.security.check_open_ports") as mock_ports, \
             patch("merlya.tools.security.check_security_config") as mock_sec, \
             patch("merlya.tools.security.check_users") as mock_users:

            mock_ports.return_value = MagicMock(success=True, data=[])
            mock_sec.return_value = MagicMock(success=True, data={"issues": []})
            mock_users.return_value = MagicMock(
                success=True, data={"sudo_users": [], "shell_users": []}
            )

            result = await cmd_scan(mock_context, ["testserver", "--security"])

            assert result.success
            mock_ports.assert_called_once()


class TestScanOutput:
    """Tests for scan output formatting."""

    @pytest.fixture
    def mock_context(self) -> MagicMock:
        """Create a mock context."""
        ctx = MagicMock()
        ctx.hosts = AsyncMock()
        ctx.hosts.get_by_name = AsyncMock(
            return_value=Host(name="test", hostname="10.0.0.1", port=22)
        )
        ctx.ui = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_output_includes_host_name(self, mock_context: MagicMock) -> None:
        """Test output includes host name."""
        with patch("merlya.tools.system.get_system_info") as mock_sys, \
             patch("merlya.tools.system.check_memory") as mock_mem, \
             patch("merlya.tools.system.check_cpu") as mock_cpu, \
             patch("merlya.tools.system.check_disk_usage") as mock_disk:

            mock_sys.return_value = MagicMock(success=True, data={})
            mock_mem.return_value = MagicMock(success=True, data={})
            mock_cpu.return_value = MagicMock(success=True, data={})
            mock_disk.return_value = MagicMock(success=True, data={})

            result = await cmd_scan(mock_context, ["test", "--system"])

            assert "test" in result.message
            assert "Scan Results" in result.message

    @pytest.mark.asyncio
    async def test_output_warning_icons(self, mock_context: MagicMock) -> None:
        """Test warning icons appear for high usage."""
        with patch("merlya.tools.system.get_system_info") as mock_sys, \
             patch("merlya.tools.system.check_memory") as mock_mem, \
             patch("merlya.tools.system.check_cpu") as mock_cpu, \
             patch("merlya.tools.system.check_disk_usage") as mock_disk:

            mock_sys.return_value = MagicMock(success=True, data={})
            mock_mem.return_value = MagicMock(
                success=True, data={"warning": True, "use_percent": 95}
            )
            mock_cpu.return_value = MagicMock(success=True, data={})
            mock_disk.return_value = MagicMock(success=True, data={})

            result = await cmd_scan(mock_context, ["test", "--system"])

            # Should have warning emoji for high memory
            assert "⚠️" in result.message or "warning" in result.message.lower()

    @pytest.mark.asyncio
    async def test_output_limits_ports(self, mock_context: MagicMock) -> None:
        """Test port list is limited to 10."""
        with patch("merlya.tools.security.check_open_ports") as mock_ports, \
             patch("merlya.tools.security.check_security_config") as mock_sec, \
             patch("merlya.tools.security.check_users") as mock_users:

            # Create 15 ports
            ports = [{"port": i, "proto": "tcp", "process": "test"} for i in range(15)]
            mock_ports.return_value = MagicMock(success=True, data=ports)
            mock_sec.return_value = MagicMock(success=True, data={"issues": []})
            mock_users.return_value = MagicMock(
                success=True, data={"sudo_users": [], "shell_users": []}
            )

            result = await cmd_scan(mock_context, ["test", "--security"])

            # Should mention "and X more"
            assert "5 more" in result.message


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
