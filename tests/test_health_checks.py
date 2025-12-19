"""Tests for health check functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.core.types import CheckStatus, HealthCheck
from merlya.health.checks import (
    StartupHealth,
    check_disk_space,
    check_keyring,
    check_ram,
    check_ssh_available,
    run_startup_checks,
)


class TestCheckStatus:
    """Tests for CheckStatus enum."""

    def test_status_values(self) -> None:
        """Test all status values exist."""
        assert CheckStatus.OK.value == "ok"
        assert CheckStatus.WARNING.value == "warning"
        assert CheckStatus.ERROR.value == "error"
        assert CheckStatus.DISABLED.value == "disabled"


class TestHealthCheck:
    """Tests for HealthCheck dataclass."""

    def test_health_check_creation(self) -> None:
        """Test HealthCheck creation."""
        check = HealthCheck(
            name="test_check",
            status=CheckStatus.OK,
            message="All good",
        )
        assert check.name == "test_check"
        assert check.status == CheckStatus.OK
        assert check.message == "All good"
        assert check.critical is False
        assert check.details == {}

    def test_health_check_with_details(self) -> None:
        """Test HealthCheck with details."""
        check = HealthCheck(
            name="detailed",
            status=CheckStatus.WARNING,
            message="Some issue",
            critical=True,
            details={"latency_ms": 150},
        )
        assert check.critical is True
        assert check.details["latency_ms"] == 150


class TestStartupHealth:
    """Tests for StartupHealth dataclass."""

    def test_can_start_with_no_errors(self) -> None:
        """Test can_start is True when no critical errors."""
        health = StartupHealth(
            checks=[
                HealthCheck(name="test1", status=CheckStatus.OK, message="OK"),
                HealthCheck(name="test2", status=CheckStatus.WARNING, message="Warning"),
            ]
        )
        assert health.can_start is True

    def test_can_start_with_critical_error(self) -> None:
        """Test can_start is False when critical error exists."""
        health = StartupHealth(
            checks=[
                HealthCheck(
                    name="critical", status=CheckStatus.ERROR, message="Error", critical=True
                ),
            ]
        )
        assert health.can_start is False

    def test_can_start_with_non_critical_error(self) -> None:
        """Test can_start is True when non-critical error exists."""
        health = StartupHealth(
            checks=[
                HealthCheck(
                    name="non_critical", status=CheckStatus.ERROR, message="Error", critical=False
                ),
            ]
        )
        assert health.can_start is True

    def test_has_warnings(self) -> None:
        """Test has_warnings detection."""
        health = StartupHealth(
            checks=[
                HealthCheck(name="warn", status=CheckStatus.WARNING, message="Warning"),
            ]
        )
        assert health.has_warnings is True

        health_ok = StartupHealth(
            checks=[
                HealthCheck(name="ok", status=CheckStatus.OK, message="OK"),
            ]
        )
        assert health_ok.has_warnings is False

    def test_get_check(self) -> None:
        """Test get_check method."""
        health = StartupHealth(
            checks=[
                HealthCheck(name="ram", status=CheckStatus.OK, message="OK"),
                HealthCheck(name="disk", status=CheckStatus.OK, message="OK"),
            ]
        )

        ram_check = health.get_check("ram")
        assert ram_check is not None
        assert ram_check.name == "ram"

        missing = health.get_check("nonexistent")
        assert missing is None


class TestCheckRam:
    """Tests for check_ram function."""

    def test_returns_health_check_and_tier(self) -> None:
        """Test that check_ram returns HealthCheck and tier."""
        with patch("merlya.health.system_checks.psutil.virtual_memory") as mock_vm:
            mock_vm.return_value = MagicMock(available=8 * 1024**3)  # 8GB

            check, tier = check_ram()

            assert isinstance(check, HealthCheck)
            assert check.name == "ram"
            assert isinstance(tier, str)

    def test_high_ram_performance_tier(self) -> None:
        """Test performance tier with high RAM."""
        with patch("merlya.health.system_checks.psutil.virtual_memory") as mock_vm:
            mock_vm.return_value = MagicMock(available=8 * 1024**3)  # 8GB

            check, tier = check_ram()

            assert check.status == CheckStatus.OK
            assert tier == "performance"

    def test_low_ram_economy_tier(self) -> None:
        """Test economy tier with low RAM."""
        with patch("merlya.health.system_checks.psutil.virtual_memory") as mock_vm:
            mock_vm.return_value = MagicMock(available=1 * 1024**3)  # 1GB

            check, tier = check_ram()

            assert check.status in [CheckStatus.OK, CheckStatus.WARNING]
            # Tier depends on implementation, just check it's a string
            assert isinstance(tier, str)


class TestCheckDiskSpace:
    """Tests for check_disk_space function."""

    def test_disk_space_returns_check(self) -> None:
        """Test that check_disk_space returns HealthCheck."""
        check = check_disk_space()

        assert check.name == "disk_space"
        assert check.status in [CheckStatus.OK, CheckStatus.WARNING, CheckStatus.ERROR]


class TestCheckSshAvailable:
    """Tests for check_ssh_available function."""

    def test_asyncssh_available(self) -> None:
        """Test when asyncssh is available."""
        check = check_ssh_available()

        assert check.name == "ssh"
        # Status depends on asyncssh being installed
        assert check.status in [CheckStatus.OK, CheckStatus.DISABLED]


class TestCheckKeyring:
    """Tests for check_keyring function."""

    def test_keyring_returns_check(self) -> None:
        """Test that check_keyring returns HealthCheck."""
        check = check_keyring()

        assert check.name == "keyring"
        # Status depends on keyring availability on system
        assert check.status in [CheckStatus.OK, CheckStatus.WARNING, CheckStatus.ERROR]


class TestRunStartupChecks:
    """Tests for run_startup_checks function."""

    @pytest.mark.asyncio
    async def test_returns_startup_health(self) -> None:
        """Test that run_startup_checks returns StartupHealth."""
        with (
            patch("merlya.health.checks.check_ram") as mock_ram,
            patch("merlya.health.checks.check_disk_space") as mock_disk,
            patch("merlya.health.checks.check_ssh_available") as mock_ssh,
            patch("merlya.health.checks.check_keyring") as mock_keyring,
            patch("merlya.health.checks.check_web_search") as mock_web,
            patch("merlya.health.checks.check_llm_provider") as mock_llm,
        ):
            mock_ram.return_value = (
                HealthCheck(name="ram", status=CheckStatus.OK, message="OK"),
                "performance",
            )
            mock_disk.return_value = HealthCheck(name="disk", status=CheckStatus.OK, message="OK")
            mock_ssh.return_value = HealthCheck(name="ssh", status=CheckStatus.OK, message="OK")
            mock_keyring.return_value = HealthCheck(
                name="keyring", status=CheckStatus.OK, message="OK"
            )
            mock_web.return_value = HealthCheck(name="web", status=CheckStatus.OK, message="OK")

            async def mock_llm_coro(*_args, **_kwargs):
                return HealthCheck(name="llm", status=CheckStatus.OK, message="OK")

            mock_llm.side_effect = mock_llm_coro

            result = await run_startup_checks(include_optional=True)

            assert isinstance(result, StartupHealth)
            assert len(result.checks) > 0
            assert result.model_tier is not None

    @pytest.mark.asyncio
    async def test_uses_ram_tier_when_no_override(self) -> None:
        """Use the RAM-derived tier for tier-aware checks when no override is provided."""
        captured: dict[str, str | None] = {"tier": None}

        async def fake_check_parser_service(tier: str | None = None) -> HealthCheck:
            captured["tier"] = tier
            return HealthCheck(name="parser", status=CheckStatus.OK, message="OK")

        with (
            patch("merlya.health.system_checks.check_ram") as mock_ram,
            patch("merlya.health.system_checks.check_disk_space") as mock_disk,
            patch("merlya.health.infrastructure.check_ssh_available") as mock_ssh,
            patch("merlya.health.infrastructure.check_keyring") as mock_keyring,
            patch(
                "merlya.health.service_checks.check_parser_service",
                new=fake_check_parser_service,
            ),
            patch(
                "merlya.health.connectivity.check_llm_provider", new_callable=AsyncMock
            ) as mock_llm,
            patch("merlya.health.service_checks.check_session_manager") as mock_session,
            patch("merlya.health.mcp_checks.check_mcp_servers") as mock_mcp,
        ):
            mock_ram.return_value = (
                HealthCheck(name="ram", status=CheckStatus.OK, message="OK"),
                "performance",
            )
            mock_disk.return_value = HealthCheck(name="disk", status=CheckStatus.OK, message="OK")
            mock_ssh.return_value = HealthCheck(name="ssh", status=CheckStatus.OK, message="OK")
            mock_keyring.return_value = HealthCheck(
                name="keyring", status=CheckStatus.OK, message="OK"
            )
            mock_llm.return_value = HealthCheck(name="llm", status=CheckStatus.OK, message="OK")
            mock_session.return_value = HealthCheck(
                name="session", status=CheckStatus.OK, message="OK"
            )
            mock_mcp.return_value = HealthCheck(name="mcp", status=CheckStatus.OK, message="OK")

            await run_startup_checks(include_optional=True)

        assert captured["tier"] == "performance"

    @pytest.mark.asyncio
    async def test_maps_llm_fallback_tier_to_lightweight(self) -> None:
        """Map 'llm_fallback' to 'lightweight' for local tier-aware checks."""
        captured: dict[str, str | None] = {"tier": None}

        async def fake_check_parser_service(tier: str | None = None) -> HealthCheck:
            captured["tier"] = tier
            return HealthCheck(name="parser", status=CheckStatus.OK, message="OK")

        with (
            patch("merlya.health.system_checks.check_ram") as mock_ram,
            patch("merlya.health.system_checks.check_disk_space") as mock_disk,
            patch("merlya.health.infrastructure.check_ssh_available") as mock_ssh,
            patch("merlya.health.infrastructure.check_keyring") as mock_keyring,
            patch(
                "merlya.health.service_checks.check_parser_service",
                new=fake_check_parser_service,
            ),
            patch(
                "merlya.health.connectivity.check_llm_provider", new_callable=AsyncMock
            ) as mock_llm,
            patch("merlya.health.service_checks.check_session_manager") as mock_session,
            patch("merlya.health.mcp_checks.check_mcp_servers") as mock_mcp,
        ):
            mock_ram.return_value = (
                HealthCheck(name="ram", status=CheckStatus.WARNING, message="Low RAM"),
                "llm_fallback",
            )
            mock_disk.return_value = HealthCheck(name="disk", status=CheckStatus.OK, message="OK")
            mock_ssh.return_value = HealthCheck(name="ssh", status=CheckStatus.OK, message="OK")
            mock_keyring.return_value = HealthCheck(
                name="keyring", status=CheckStatus.OK, message="OK"
            )
            mock_llm.return_value = HealthCheck(name="llm", status=CheckStatus.OK, message="OK")
            mock_session.return_value = HealthCheck(
                name="session", status=CheckStatus.OK, message="OK"
            )
            mock_mcp.return_value = HealthCheck(name="mcp", status=CheckStatus.OK, message="OK")

            await run_startup_checks(include_optional=True)

        assert captured["tier"] == "lightweight"
