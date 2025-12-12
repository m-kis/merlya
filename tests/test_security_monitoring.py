"""
Tests for security monitoring tools.

Covers merlya.tools.security.monitoring parsing helpers and public checks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.tools.security.monitoring import (
    _parse_failed_logins,
    _parse_services,
    _parse_updates,
    check_critical_services,
    check_failed_logins,
    check_pending_updates,
)


@pytest.fixture
def mock_context() -> MagicMock:
    """Minimal SharedContext mock for monitoring tools."""
    return MagicMock()


class TestParseFailedLogins:
    """Unit tests for _parse_failed_logins."""

    def test_empty_stdout_returns_empty_structures(self) -> None:
        attempts, counts = _parse_failed_logins("")
        assert attempts == []
        assert counts == {}

    def test_extracts_ips_and_counts(self) -> None:
        stdout = "\n".join(
            [
                "Failed password for root from 1.2.3.4 port 22",
                "Invalid user test from 1.2.3.4 port 2222",
                "refused connect from 5.6.7.8",
            ]
        )
        attempts, counts = _parse_failed_logins(stdout)
        assert len(attempts) == 3
        assert counts == {"1.2.3.4": 2, "5.6.7.8": 1}


class TestCheckFailedLogins:
    """Tests for check_failed_logins."""

    @pytest.mark.asyncio
    async def test_clamps_hours_and_sets_warning_severity(self, mock_context: MagicMock) -> None:
        lines = [f"Failed password from 10.0.0.1 attempt {_}" for _ in range(25)]
        mock_result = MagicMock(exit_code=0, stdout="\n".join(lines))

        with patch(
            "merlya.tools.security.monitoring.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            result = await check_failed_logins(mock_context, "web-01", hours=999)

        assert result.success is True
        assert result.severity == "warning"
        assert result.data["hours_checked"] == 168
        assert result.data["total_attempts"] == 25
        assert result.data["top_ips"][0]["ip"] == "10.0.0.1"


class TestParseUpdates:
    """Unit tests for _parse_updates."""

    def test_parses_pkg_manager_and_security_flags(self) -> None:
        stdout = "PKG_MANAGER:apt\nopenssl/security 1.0\nbash 5.0\n"
        updates, manager = _parse_updates(stdout)

        assert manager == "apt"
        assert updates == [
            {"package": "openssl", "security": True},
            {"package": "bash", "security": False},
        ]


class TestCheckPendingUpdates:
    """Tests for check_pending_updates."""

    @pytest.mark.asyncio
    async def test_critical_when_many_security_updates(self, mock_context: MagicMock) -> None:
        security_lines = [f"pkg{i}/security 1.0" for i in range(6)]
        stdout = "PKG_MANAGER:apt\n" + "\n".join(security_lines)
        mock_result = MagicMock(exit_code=0, stdout=stdout)

        with patch(
            "merlya.tools.security.monitoring.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            result = await check_pending_updates(mock_context, "web-01")

        assert result.success is True
        assert result.severity == "critical"
        assert result.data["security_updates"] == 6
        assert result.data["total_updates"] == 6
        assert result.data["package_manager"] == "apt"


class TestParseServices:
    """Unit tests for _parse_services."""

    def test_parses_service_lines_and_counts_inactive(self) -> None:
        stdout = "SERVICES:sshd ufw\nsshd:active\nufw:inactive\nmissing:not-found\n"
        services, inactive = _parse_services(stdout)

        assert inactive == 1
        assert services == [
            {"service": "sshd", "status": "active", "active": True},
            {"service": "ufw", "status": "inactive", "active": False},
            {"service": "missing", "status": "not-found", "active": False},
        ]


class TestCheckCriticalServices:
    """Tests for check_critical_services."""

    @pytest.mark.asyncio
    async def test_returns_error_when_no_valid_services(self, mock_context: MagicMock) -> None:
        result = await check_critical_services(mock_context, "web-01", services=["bad name", "###"])
        assert result.success is False
        assert "No valid service names" in result.error

    @pytest.mark.asyncio
    async def test_sets_critical_when_sshd_inactive(self, mock_context: MagicMock) -> None:
        stdout = "SERVICES:sshd ufw\nsshd:inactive\nufw:active\n"
        mock_result = MagicMock(exit_code=0, stdout=stdout)

        with patch(
            "merlya.tools.security.monitoring.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            result = await check_critical_services(mock_context, "web-01", services=["sshd", "ufw"])

        assert result.success is True
        assert result.severity == "critical"
        assert result.data["inactive_count"] == 1
