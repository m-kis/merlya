"""Tests for merlya.tools.system.tools module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.tools.core import ToolResult
from merlya.tools.system.tools import (
    _validate_path,
    _validate_service_name,
    _validate_username,
    analyze_logs,
    check_all_disks,
    check_cpu,
    check_disk_usage,
    check_docker,
    check_memory,
    check_service_status,
    get_system_info,
    list_processes,
)

# ==============================================================================
# TestValidatePath
# ==============================================================================


class TestValidatePath:
    """Tests for _validate_path function."""

    def test_valid_path(self) -> None:
        """Test valid paths return None."""
        assert _validate_path("/var/log/syslog") is None
        assert _validate_path("/etc/passwd") is None
        assert _validate_path("./relative") is None

    def test_empty_path(self) -> None:
        """Test empty path returns error."""
        assert _validate_path("") == "Path cannot be empty"

    def test_path_with_null_bytes(self) -> None:
        """Test path with null bytes returns error."""
        assert _validate_path("/path\x00/to") == "Path contains null bytes"

    def test_path_too_long(self) -> None:
        """Test path exceeding max length."""
        long_path = "/" + "a" * 5000
        assert "too long" in _validate_path(long_path)


# ==============================================================================
# TestValidateServiceName
# ==============================================================================


class TestValidateServiceName:
    """Tests for _validate_service_name function."""

    def test_valid_service_names(self) -> None:
        """Test valid service names."""
        assert _validate_service_name("nginx") is None
        assert _validate_service_name("ssh.service") is None
        assert _validate_service_name("mysql-server") is None
        assert _validate_service_name("node_exporter") is None
        assert _validate_service_name("service.name.with.dots") is None

    def test_empty_service_name(self) -> None:
        """Test empty service name returns error."""
        assert _validate_service_name("") == "Service name cannot be empty"

    def test_service_name_too_long(self) -> None:
        """Test service name exceeding max length."""
        long_name = "a" * 200
        assert "too long" in _validate_service_name(long_name)

    def test_invalid_service_name_characters(self) -> None:
        """Test service name with invalid characters."""
        assert "Invalid" in _validate_service_name("service name")  # space
        assert "Invalid" in _validate_service_name("service@name")  # @
        assert "Invalid" in _validate_service_name("service/name")  # /
        assert "Invalid" in _validate_service_name("service;name")  # ;


# ==============================================================================
# TestValidateUsername
# ==============================================================================


class TestValidateUsername:
    """Tests for _validate_username function."""

    def test_valid_usernames(self) -> None:
        """Test valid usernames."""
        assert _validate_username("root") is None
        assert _validate_username("www-data") is None
        assert _validate_username("user_123") is None

    def test_none_username(self) -> None:
        """Test None username is allowed."""
        assert _validate_username(None) is None

    def test_empty_username(self) -> None:
        """Test empty username is allowed (treated as optional)."""
        assert _validate_username("") is None

    def test_username_too_long(self) -> None:
        """Test username exceeding max length."""
        long_name = "a" * 50
        assert "too long" in _validate_username(long_name)

    def test_invalid_username_characters(self) -> None:
        """Test username with invalid characters."""
        assert "Invalid" in _validate_username("user@host")
        assert "Invalid" in _validate_username("user name")
        assert "Invalid" in _validate_username("user.name")


# ==============================================================================
# TestGetSystemInfo
# ==============================================================================


class TestGetSystemInfo:
    """Tests for get_system_info function."""

    @pytest.mark.asyncio
    async def test_get_system_info_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful system info retrieval."""
        mock_results = [
            ToolResult(success=True, data={"stdout": "web-01"}),  # hostname
            ToolResult(success=True, data={"stdout": "Ubuntu 22.04 LTS"}),  # os
            ToolResult(success=True, data={"stdout": "5.15.0-91-generic"}),  # kernel
            ToolResult(success=True, data={"stdout": "x86_64"}),  # arch
            ToolResult(success=True, data={"stdout": "up 5 days, 3 hours"}),  # uptime
            ToolResult(success=True, data={"stdout": "0.52 0.58 0.59"}),  # load
        ]

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.side_effect = mock_results
            result = await get_system_info(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["hostname"] == "web-01"
        assert result.data["os"] == "Ubuntu 22.04 LTS"
        assert result.data["kernel"] == "5.15.0-91-generic"

    @pytest.mark.asyncio
    async def test_get_system_info_partial_failure(self, mock_shared_context: MagicMock) -> None:
        """Test system info with some commands failing."""
        mock_results = [
            ToolResult(success=True, data={"stdout": "web-01"}),  # hostname
            ToolResult(success=False, data={}, error="Command failed"),  # os
            ToolResult(success=True, data={"stdout": "5.15.0"}),  # kernel
            ToolResult(success=False, data={}, error="Not found"),  # arch
            ToolResult(success=True, data={"stdout": "up 1 day"}),  # uptime
            ToolResult(success=True, data={"stdout": "0.1 0.2 0.3"}),  # load
        ]

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.side_effect = mock_results
            result = await get_system_info(mock_shared_context, "web-01")

        assert result.success is True
        assert "hostname" in result.data
        assert "kernel" in result.data
        # os and arch should be missing due to failures
        assert "os" not in result.data or result.data.get("os") == ""

    @pytest.mark.asyncio
    async def test_get_system_info_all_failed(self, mock_shared_context: MagicMock) -> None:
        """Test system info when all commands fail."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=False, data={}, error="Connection failed")
            result = await get_system_info(mock_shared_context, "web-01")

        assert result.success is False
        assert "Failed" in result.error


# ==============================================================================
# TestCheckDiskUsage
# ==============================================================================


class TestCheckDiskUsage:
    """Tests for check_disk_usage function."""

    @pytest.mark.asyncio
    async def test_check_disk_usage_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful disk usage check."""
        df_output = "/dev/sda1 50G 25G 23G 53% /"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": df_output})
            result = await check_disk_usage(mock_shared_context, "web-01", "/")

        assert result.success is True
        assert result.data["filesystem"] == "/dev/sda1"
        assert result.data["size"] == "50G"
        assert result.data["used"] == "25G"
        assert result.data["use_percent"] == 53
        assert result.data["warning"] is False

    @pytest.mark.asyncio
    async def test_check_disk_usage_warning(self, mock_shared_context: MagicMock) -> None:
        """Test disk usage with warning threshold exceeded."""
        df_output = "/dev/sda1 50G 47G 2G 95% /"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": df_output})
            result = await check_disk_usage(mock_shared_context, "web-01", "/", threshold=90)

        assert result.success is True
        assert result.data["use_percent"] == 95
        assert result.data["warning"] is True

    @pytest.mark.asyncio
    async def test_check_disk_usage_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test disk usage with invalid path."""
        result = await check_disk_usage(mock_shared_context, "web-01", "")
        assert result.success is False
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_check_disk_usage_invalid_threshold(self, mock_shared_context: MagicMock) -> None:
        """Test disk usage with invalid threshold."""
        result = await check_disk_usage(mock_shared_context, "web-01", "/", threshold=150)
        assert result.success is False
        assert "0-100" in result.error

    @pytest.mark.asyncio
    async def test_check_disk_usage_parse_failure(self, mock_shared_context: MagicMock) -> None:
        """Test disk usage with unparseable output."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": "invalid output"})
            result = await check_disk_usage(mock_shared_context, "web-01", "/")

        assert result.success is False
        assert "parse" in result.error.lower()


# ==============================================================================
# TestCheckMemory
# ==============================================================================


class TestCheckMemory:
    """Tests for check_memory function."""

    @pytest.mark.asyncio
    async def test_check_memory_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful memory check."""
        # Now uses free -b (bytes) for precision, so we provide bytes
        # 7982 MB = 7982 * 1024 * 1024 bytes
        total_bytes = 7982 * 1024 * 1024
        used_bytes = 2156 * 1024 * 1024
        free_bytes = 3421 * 1024 * 1024
        shared_bytes = 256 * 1024 * 1024
        buffers_bytes = 2404 * 1024 * 1024
        available_bytes = 5289 * 1024 * 1024
        free_output = (
            f"              total        used        free      shared  buff/cache   available\n"
            f"Mem:    {total_bytes}  {used_bytes}  {free_bytes}  {shared_bytes}  {buffers_bytes}  {available_bytes}"
        )

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": free_output})
            result = await check_memory(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["total_mb"] == 7982
        assert result.data["used_mb"] == 2156
        assert result.data["available_mb"] == 5289
        assert "use_percent" in result.data

    @pytest.mark.asyncio
    async def test_check_memory_warning(self, mock_shared_context: MagicMock) -> None:
        """Test memory with warning threshold exceeded."""
        # High memory usage: ~95% (in bytes)
        total_bytes = 8000 * 1024 * 1024
        used_bytes = 7600 * 1024 * 1024
        free_bytes = 200 * 1024 * 1024
        shared_bytes = 100 * 1024 * 1024
        buffers_bytes = 200 * 1024 * 1024
        available_bytes = 200 * 1024 * 1024
        free_output = (
            f"              total        used        free      shared  buff/cache   available\n"
            f"Mem:    {total_bytes}  {used_bytes}  {free_bytes}  {shared_bytes}  {buffers_bytes}  {available_bytes}"
        )

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": free_output})
            result = await check_memory(mock_shared_context, "web-01", threshold=90)

        assert result.success is True
        assert result.data["warning"] is True

    @pytest.mark.asyncio
    async def test_check_memory_invalid_threshold(self, mock_shared_context: MagicMock) -> None:
        """Test memory with invalid threshold."""
        result = await check_memory(mock_shared_context, "web-01", threshold=-10)
        assert result.success is False
        assert "0-100" in result.error

    @pytest.mark.asyncio
    async def test_check_memory_parse_failure(self, mock_shared_context: MagicMock) -> None:
        """Test memory with unparseable output."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": "bad output"})
            result = await check_memory(mock_shared_context, "web-01")

        assert result.success is False


# ==============================================================================
# TestCheckCPU
# ==============================================================================


class TestCheckCPU:
    """Tests for check_cpu function."""

    @pytest.mark.asyncio
    async def test_check_cpu_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful CPU check."""
        loadavg_output = "0.52 0.58 0.59 2/1234 12345\n4"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": loadavg_output})
            result = await check_cpu(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["load_1m"] == 0.52
        assert result.data["load_5m"] == 0.58
        assert result.data["load_15m"] == 0.59
        assert result.data["cpu_count"] == 4
        assert "use_percent" in result.data

    @pytest.mark.asyncio
    async def test_check_cpu_high_load_warning(self, mock_shared_context: MagicMock) -> None:
        """Test CPU with high load warning."""
        # 4 CPUs with load 4.0 = 100% usage
        loadavg_output = "4.0 3.5 3.0 1/100 1234\n4"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": loadavg_output})
            result = await check_cpu(mock_shared_context, "web-01", threshold=80)

        assert result.success is True
        assert result.data["warning"] is True

    @pytest.mark.asyncio
    async def test_check_cpu_invalid_threshold(self, mock_shared_context: MagicMock) -> None:
        """Test CPU with invalid threshold."""
        result = await check_cpu(mock_shared_context, "web-01", threshold=200)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_check_cpu_parse_failure(self, mock_shared_context: MagicMock) -> None:
        """Test CPU with unparseable output."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": "bad"})
            result = await check_cpu(mock_shared_context, "web-01")

        assert result.success is False


# ==============================================================================
# TestListProcesses
# ==============================================================================


class TestListProcesses:
    """Tests for list_processes function."""

    @pytest.mark.asyncio
    async def test_list_processes_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful process listing."""
        ps_output = """USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root         1  0.0  0.1 169104 13256 ?        Ss   Dec01   0:12 /sbin/init
www-data  1234  0.5  1.2 456789 98765 ?        S    10:00   1:23 nginx: worker process"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ps_output})
            result = await list_processes(mock_shared_context, "web-01")

        assert result.success is True
        assert len(result.data) == 2
        assert result.data[0]["user"] == "root"
        assert result.data[0]["pid"] == 1
        assert result.data[1]["user"] == "www-data"

    @pytest.mark.asyncio
    async def test_list_processes_with_user_filter(self, mock_shared_context: MagicMock) -> None:
        """Test process listing filtered by user."""
        ps_output = """USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
www-data  1234  0.5  1.2 456789 98765 ?        S    10:00   1:23 nginx"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ps_output})
            result = await list_processes(mock_shared_context, "web-01", user="www-data")

        assert result.success is True
        # Verify user filter was applied in command
        call_args = mock_ssh.call_args[0]
        assert "www-data" in call_args[2]

    @pytest.mark.asyncio
    async def test_list_processes_with_name_filter(self, mock_shared_context: MagicMock) -> None:
        """Test process listing filtered by name."""
        ps_output = """USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root      5678  1.0  2.0 123456 54321 ?        Sl   Dec01  45:67 nginx: master"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ps_output})
            result = await list_processes(mock_shared_context, "web-01", filter_name="nginx")

        assert result.success is True
        call_args = mock_ssh.call_args[0]
        assert "nginx" in call_args[2]

    @pytest.mark.asyncio
    async def test_list_processes_invalid_user(self, mock_shared_context: MagicMock) -> None:
        """Test process listing with invalid username."""
        result = await list_processes(mock_shared_context, "web-01", user="invalid@user")
        assert result.success is False
        assert "Invalid" in result.error

    @pytest.mark.asyncio
    async def test_list_processes_invalid_limit(self, mock_shared_context: MagicMock) -> None:
        """Test process listing with invalid limit."""
        result = await list_processes(mock_shared_context, "web-01", limit=0)
        assert result.success is False
        assert "1-1000" in result.error

    @pytest.mark.asyncio
    async def test_list_processes_filter_too_long(self, mock_shared_context: MagicMock) -> None:
        """Test process listing with filter too long."""
        long_filter = "a" * 300
        result = await list_processes(mock_shared_context, "web-01", filter_name=long_filter)
        assert result.success is False
        assert "too long" in result.error.lower()


# ==============================================================================
# TestCheckServiceStatus
# ==============================================================================


class TestCheckServiceStatus:
    """Tests for check_service_status function."""

    @pytest.mark.asyncio
    async def test_check_service_active(self, mock_shared_context: MagicMock) -> None:
        """Test checking active service."""
        status_output = """active
ActiveState=active
SubState=running
MainPID=1234"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": status_output})
            result = await check_service_status(mock_shared_context, "web-01", "nginx")

        assert result.success is True
        assert result.data["service"] == "nginx"
        assert result.data["active"] is True
        assert result.data["status"] == "active"
        assert result.data["activestate"] == "active"
        assert result.data["mainpid"] == "1234"

    @pytest.mark.asyncio
    async def test_check_service_inactive(self, mock_shared_context: MagicMock) -> None:
        """Test checking inactive service."""
        status_output = "inactive"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(
                success=True, data={"stdout": status_output, "stderr": "Unit not active"}
            )
            result = await check_service_status(mock_shared_context, "web-01", "nginx")

        assert result.success is True
        assert result.data["active"] is False

    @pytest.mark.asyncio
    async def test_check_service_invalid_name(self, mock_shared_context: MagicMock) -> None:
        """Test checking service with invalid name."""
        result = await check_service_status(mock_shared_context, "web-01", "service; rm -rf /")
        assert result.success is False
        assert "Invalid" in result.error

    @pytest.mark.asyncio
    async def test_check_service_empty_name(self, mock_shared_context: MagicMock) -> None:
        """Test checking service with empty name."""
        result = await check_service_status(mock_shared_context, "web-01", "")
        assert result.success is False
        assert "empty" in result.error.lower()


# ==============================================================================
# TestAnalyzeLogs
# ==============================================================================


class TestAnalyzeLogs:
    """Tests for analyze_logs function."""

    @pytest.mark.asyncio
    async def test_analyze_logs_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful log analysis."""
        log_output = """Dec 12 10:00:00 web-01 systemd[1]: Started service
Dec 12 10:00:01 web-01 nginx[1234]: Starting nginx
Dec 12 10:00:02 web-01 nginx[1234]: Listening on port 80"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": log_output})
            result = await analyze_logs(mock_shared_context, "web-01", "/var/log/syslog")

        assert result.success is True
        assert result.data["path"] == "/var/log/syslog"
        assert result.data["count"] == 3

    @pytest.mark.asyncio
    async def test_analyze_logs_with_pattern(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with pattern filter."""
        log_output = "Dec 12 10:00:01 web-01 nginx[1234]: error"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": log_output})
            result = await analyze_logs(
                mock_shared_context, "web-01", "/var/log/syslog", pattern="nginx"
            )

        assert result.success is True
        call_args = mock_ssh.call_args[0]
        assert "grep" in call_args[2] and "nginx" in call_args[2]

    @pytest.mark.asyncio
    async def test_analyze_logs_with_level_error(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with error level filter."""
        log_output = "Dec 12 10:00:01 web-01 app: ERROR Something went wrong"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": log_output})
            result = await analyze_logs(
                mock_shared_context, "web-01", "/var/log/syslog", level="error"
            )

        assert result.success is True
        call_args = mock_ssh.call_args[0]
        assert "error" in call_args[2].lower()

    @pytest.mark.asyncio
    async def test_analyze_logs_with_level_warn(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with warn level filter."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ""})
            await analyze_logs(mock_shared_context, "web-01", "/var/log/syslog", level="warn")
            call_args = mock_ssh.call_args[0]
            assert "warn" in call_args[2].lower()

    @pytest.mark.asyncio
    async def test_analyze_logs_with_level_info(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with info level filter."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ""})
            await analyze_logs(mock_shared_context, "web-01", "/var/log/syslog", level="info")
            call_args = mock_ssh.call_args[0]
            assert "info" in call_args[2].lower()

    @pytest.mark.asyncio
    async def test_analyze_logs_with_level_debug(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with debug level filter."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ""})
            await analyze_logs(mock_shared_context, "web-01", "/var/log/syslog", level="debug")
            call_args = mock_ssh.call_args[0]
            assert "debug" in call_args[2].lower()

    @pytest.mark.asyncio
    async def test_analyze_logs_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with invalid path."""
        result = await analyze_logs(mock_shared_context, "web-01", "")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_analyze_logs_invalid_level(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with invalid level."""
        result = await analyze_logs(
            mock_shared_context, "web-01", "/var/log/syslog", level="invalid"
        )
        assert result.success is False
        assert "Invalid level" in result.error

    @pytest.mark.asyncio
    async def test_analyze_logs_invalid_lines(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with invalid lines count."""
        result = await analyze_logs(mock_shared_context, "web-01", "/var/log/syslog", lines=0)
        assert result.success is False
        assert "1-10000" in result.error

    @pytest.mark.asyncio
    async def test_analyze_logs_pattern_too_long(self, mock_shared_context: MagicMock) -> None:
        """Test log analysis with pattern too long."""
        long_pattern = "a" * 300
        result = await analyze_logs(
            mock_shared_context, "web-01", "/var/log/syslog", pattern=long_pattern
        )
        assert result.success is False
        assert "too long" in result.error.lower()


# ==============================================================================
# TestCheckAllDisks
# ==============================================================================


class TestCheckAllDisks:
    """Tests for check_all_disks function."""

    @pytest.mark.asyncio
    async def test_check_all_disks_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful all disks check."""
        df_output = """Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        50G   25G   23G  53% /
/dev/sdb1       100G   80G   15G  85% /data"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": df_output})
            result = await check_all_disks(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["total_count"] == 2
        assert len(result.data["disks"]) == 2
        assert result.data["disks"][0]["mount"] == "/"
        assert result.data["disks"][1]["mount"] == "/data"

    @pytest.mark.asyncio
    async def test_check_all_disks_with_warning(self, mock_shared_context: MagicMock) -> None:
        """Test all disks with warning threshold."""
        df_output = """Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        50G   47G    2G  95% /
/dev/sdb1       100G   10G   85G  10% /data"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": df_output})
            result = await check_all_disks(mock_shared_context, "web-01", threshold=90)

        assert result.success is True
        assert result.data["warnings"] == 1
        assert result.data["disks"][0]["warning"] is True
        assert result.data["disks"][1]["warning"] is False

    @pytest.mark.asyncio
    async def test_check_all_disks_invalid_threshold(self, mock_shared_context: MagicMock) -> None:
        """Test all disks with invalid threshold."""
        result = await check_all_disks(mock_shared_context, "web-01", threshold=150)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_check_all_disks_empty_output(self, mock_shared_context: MagicMock) -> None:
        """Test all disks with empty output."""
        df_output = "Filesystem      Size  Used Avail Use% Mounted on"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": df_output})
            result = await check_all_disks(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["total_count"] == 0


# ==============================================================================
# TestCheckDocker
# ==============================================================================


class TestCheckDocker:
    """Tests for check_docker function."""

    @pytest.mark.asyncio
    async def test_check_docker_running(self, mock_shared_context: MagicMock) -> None:
        """Test Docker check with running containers."""
        docker_output = """DOCKER:running
CONTAINERS:
nginx|Up 2 weeks|nginx:latest
redis|Up 2 weeks|redis:alpine
IMAGES:
nginx:latest|150MB
redis:alpine|50MB"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": docker_output})
            result = await check_docker(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["status"] == "running"
        assert result.data["total_containers"] == 2
        assert result.data["running_count"] == 2
        assert len(result.data["containers"]) == 2
        assert len(result.data["images"]) == 2

    @pytest.mark.asyncio
    async def test_check_docker_not_installed(self, mock_shared_context: MagicMock) -> None:
        """Test Docker check when not installed."""
        docker_output = "DOCKER:not-installed"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": docker_output})
            result = await check_docker(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["status"] == "not-installed"
        assert result.data["total_containers"] == 0

    @pytest.mark.asyncio
    async def test_check_docker_not_running(self, mock_shared_context: MagicMock) -> None:
        """Test Docker check when daemon not running."""
        docker_output = "DOCKER:not-running"

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": docker_output})
            result = await check_docker(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["status"] == "not-running"

    @pytest.mark.asyncio
    async def test_check_docker_with_stopped_containers(
        self, mock_shared_context: MagicMock
    ) -> None:
        """Test Docker check with mixed container states."""
        docker_output = """DOCKER:running
CONTAINERS:
nginx|Up 2 weeks|nginx:latest
app|Exited (0) 3 days ago|myapp:1.0
IMAGES:
nginx:latest|150MB"""

        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": docker_output})
            result = await check_docker(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["running_count"] == 1
        assert result.data["stopped_count"] == 1

    @pytest.mark.asyncio
    async def test_check_docker_empty_output(self, mock_shared_context: MagicMock) -> None:
        """Test Docker check with no output."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = ToolResult(success=True, data={"stdout": ""})
            result = await check_docker(mock_shared_context, "web-01")

        assert result.success is True
        assert result.data["status"] == "unknown"


# ==============================================================================
# Integration Tests
# ==============================================================================


class TestSystemToolsIntegration:
    """Integration tests for system tools."""

    @pytest.mark.asyncio
    async def test_full_system_check(self, mock_shared_context: MagicMock) -> None:
        """Test running multiple system checks."""
        with patch("merlya.tools.system.tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            # System info
            mock_ssh.side_effect = [
                ToolResult(success=True, data={"stdout": "web-01"}),
                ToolResult(success=True, data={"stdout": "Ubuntu"}),
                ToolResult(success=True, data={"stdout": "5.15.0"}),
                ToolResult(success=True, data={"stdout": "x86_64"}),
                ToolResult(success=True, data={"stdout": "up 1 day"}),
                ToolResult(success=True, data={"stdout": "0.5 0.5 0.5"}),
            ]

            info_result = await get_system_info(mock_shared_context, "web-01")
            assert info_result.success is True

            # Reset mock for disk check
            mock_ssh.side_effect = None
            mock_ssh.return_value = ToolResult(
                success=True, data={"stdout": "/dev/sda1 50G 25G 23G 53% /"}
            )

            disk_result = await check_disk_usage(mock_shared_context, "web-01", "/")
            assert disk_result.success is True
