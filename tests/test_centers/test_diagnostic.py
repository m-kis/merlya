"""Tests for DiagnosticCenter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.centers.base import CenterDeps, CenterMode, RiskLevel
from merlya.centers.diagnostic import (
    BLOCKED_COMMANDS,
    DIAGNOSTIC_TOOLS,
    DiagnosticCenter,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create mock shared context."""
    ctx = MagicMock()
    ctx.hosts = MagicMock()
    ctx.hosts.get_by_name = AsyncMock(return_value=MagicMock(name="web-01"))
    return ctx


@pytest.fixture
def mock_ssh_pool() -> MagicMock:
    """Create mock SSH pool."""
    pool = MagicMock()
    pool.execute = AsyncMock(return_value=MagicMock(stdout="output", stderr="", exit_code=0))
    return pool


@pytest.fixture
def center(mock_ctx: MagicMock) -> DiagnosticCenter:
    """Create DiagnosticCenter with mock context."""
    return DiagnosticCenter(mock_ctx)


class TestDiagnosticCenterProperties:
    """Tests for DiagnosticCenter properties."""

    def test_mode_is_diagnostic(self, center: DiagnosticCenter) -> None:
        """Test center mode is DIAGNOSTIC."""
        assert center.mode == CenterMode.DIAGNOSTIC

    def test_risk_level_is_low(self, center: DiagnosticCenter) -> None:
        """Test risk level is LOW."""
        assert center.risk_level == RiskLevel.LOW

    def test_allowed_tools_contains_read_tools(self, center: DiagnosticCenter) -> None:
        """Test allowed tools list contains expected tools."""
        tools = center.allowed_tools
        assert "ssh_execute" in tools
        assert "read_file" in tools
        assert "list_hosts" in tools
        assert "kubectl_get" in tools

    def test_allowed_tools_is_copy(self, center: DiagnosticCenter) -> None:
        """Test allowed_tools returns a copy."""
        tools1 = center.allowed_tools
        tools2 = center.allowed_tools
        assert tools1 is not tools2


class TestDiagnosticToolsList:
    """Tests for DIAGNOSTIC_TOOLS constant."""

    def test_contains_ssh_tools(self) -> None:
        """Test SSH tools are included."""
        assert "ssh_execute" in DIAGNOSTIC_TOOLS

    def test_contains_system_tools(self) -> None:
        """Test system monitoring tools are included."""
        assert "get_system_info" in DIAGNOSTIC_TOOLS
        assert "check_disk_usage" in DIAGNOSTIC_TOOLS
        assert "check_memory" in DIAGNOSTIC_TOOLS

    def test_contains_kubernetes_read_tools(self) -> None:
        """Test Kubernetes read tools are included."""
        assert "kubectl_get" in DIAGNOSTIC_TOOLS
        assert "kubectl_describe" in DIAGNOSTIC_TOOLS
        assert "kubectl_logs" in DIAGNOSTIC_TOOLS

    def test_contains_file_read_tools(self) -> None:
        """Test file read tools are included."""
        assert "read_file" in DIAGNOSTIC_TOOLS
        assert "list_directory" in DIAGNOSTIC_TOOLS


class TestBlockedCommands:
    """Tests for BLOCKED_COMMANDS constant."""

    def test_rm_is_blocked(self) -> None:
        """Test rm commands are blocked."""
        assert any("rm" in cmd for cmd in BLOCKED_COMMANDS)

    def test_systemctl_restart_is_blocked(self) -> None:
        """Test systemctl restart is blocked."""
        assert "systemctl restart" in BLOCKED_COMMANDS

    def test_reboot_is_blocked(self) -> None:
        """Test reboot is blocked."""
        assert "reboot" in BLOCKED_COMMANDS

    def test_package_install_is_blocked(self) -> None:
        """Test package installation is blocked."""
        assert "apt install" in BLOCKED_COMMANDS
        assert "yum install" in BLOCKED_COMMANDS


class TestCommandSafety:
    """Tests for command safety validation."""

    def test_safe_command_allowed(self, center: DiagnosticCenter) -> None:
        """Test safe commands are allowed."""
        assert center._is_safe_command("df -h") is True
        assert center._is_safe_command("ps aux") is True
        assert center._is_safe_command("cat /etc/hosts") is True

    def test_rm_command_blocked(self, center: DiagnosticCenter) -> None:
        """Test rm commands are blocked."""
        assert center._is_safe_command("rm file.txt") is False
        assert center._is_safe_command("rm -rf /") is False

    def test_systemctl_restart_blocked(self, center: DiagnosticCenter) -> None:
        """Test systemctl restart is blocked."""
        assert center._is_safe_command("systemctl restart nginx") is False

    def test_redirect_blocked(self, center: DiagnosticCenter) -> None:
        """Test output redirection is blocked."""
        assert center._is_safe_command("echo test > file") is False

    def test_case_insensitive_blocking(self, center: DiagnosticCenter) -> None:
        """Test blocking is case insensitive."""
        assert center._is_safe_command("RM -rf /") is False
        assert center._is_safe_command("REBOOT") is False


class TestExecuteCommand:
    """Tests for execute_command method."""

    async def test_executes_safe_command(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test executing a safe command."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

        evidence = await center.execute_command("web-01", "df -h")

        assert evidence.host == "web-01"
        assert evidence.command == "df -h"
        assert evidence.exit_code == 0
        mock_ssh_pool.execute.assert_called_once()

    async def test_blocks_unsafe_command(
        self,
        center: DiagnosticCenter,
    ) -> None:
        """Test blocking an unsafe command."""
        with pytest.raises(ValueError, match="Command blocked"):
            await center.execute_command("web-01", "rm -rf /tmp/*")

    async def test_collects_evidence(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test evidence is collected after execution."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

        await center.execute_command("web-01", "uptime")

        assert len(center._evidence) == 1
        assert center._evidence[0].command == "uptime"


class TestExecute:
    """Tests for execute method."""

    async def test_execute_returns_result(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
    ) -> None:
        """Test execute returns a CenterResult."""
        deps = CenterDeps(target="web-01", task="check disk usage")

        result = await center.execute(deps)

        assert result.mode == CenterMode.DIAGNOSTIC
        assert result.success is True

    async def test_execute_fails_for_unknown_host(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
    ) -> None:
        """Test execute fails for unknown host."""
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=None)

        deps = CenterDeps(target="unknown-host", task="check status")

        result = await center.execute(deps)

        assert result.success is False
        assert "not found" in result.message


class TestDiagnosticHelpers:
    """Tests for diagnostic helper methods."""

    async def test_check_disk_usage(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test check_disk_usage helper."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

        evidence = await center.check_disk_usage("web-01")

        assert "df -h" in evidence.command

    async def test_check_memory(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test check_memory helper."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

        evidence = await center.check_memory("web-01")

        assert "free -h" in evidence.command

    async def test_check_service(
        self,
        center: DiagnosticCenter,
        mock_ctx: MagicMock,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test check_service helper."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

        evidence = await center.check_service("web-01", "nginx")

        assert "nginx" in evidence.command
        assert "status" in evidence.command
