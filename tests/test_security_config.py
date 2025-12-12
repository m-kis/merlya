"""
Tests for security config auditing tools.

Covers merlya.tools.security.config helpers and main entrypoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.tools.security.config import (
    _check_auto_updates,
    _check_firewall,
    _check_ssh_config,
    _evaluate_ssh_setting,
    check_security_config,
)
from merlya.tools.security.config import (
    _severity_higher as config_severity_higher,
)


@pytest.fixture
def mock_context() -> MagicMock:
    """Minimal SharedContext mock for security tools."""
    return MagicMock()


class TestEvaluateSSHSetting:
    """Unit tests for _evaluate_ssh_setting."""

    @pytest.mark.parametrize(
        "key,value,expected_status,expected_severity",
        [
            ("PermitRootLogin", "yes", "warning", "warning"),
            ("PermitRootLogin", "prohibit-password", "ok", "info"),
            ("PasswordAuthentication", "yes", "warning", "warning"),
            ("PermitEmptyPasswords", "yes", "critical", "critical"),
            ("OtherSetting", "no", "ok", "info"),
        ],
    )
    def test_evaluate_cases(
        self, key: str, value: str, expected_status: str, expected_severity: str
    ) -> None:
        status, message, severity = _evaluate_ssh_setting(key, value)

        assert status == expected_status
        assert severity == expected_severity
        if expected_status != "ok":
            assert message


class TestSeverityHigher:
    """Unit tests for _severity_higher."""

    def test_severity_ordering(self) -> None:
        assert config_severity_higher("warning", "info") is True
        assert config_severity_higher("critical", "warning") is True
        assert config_severity_higher("info", "warning") is False
        assert config_severity_higher("warning", "warning") is False


class TestSSHConfigParsing:
    """Tests for SSH config parsing."""

    @pytest.mark.asyncio
    async def test_check_ssh_config_parses_lines(self, mock_context: MagicMock) -> None:
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = (
            "PermitRootLogin yes\nPasswordAuthentication no\nPermitEmptyPasswords yes\n"
        )

        with patch(
            "merlya.tools.security.config.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            checks, severity = await _check_ssh_config(mock_context, "web-01")

        assert len(checks) == 3
        assert severity == "critical"
        assert any(
            c["setting"] == "PermitEmptyPasswords" and c["status"] == "critical" for c in checks
        )

    @pytest.mark.asyncio
    async def test_check_ssh_config_command_failure_returns_empty(
        self, mock_context: MagicMock
    ) -> None:
        mock_result = MagicMock(exit_code=1, stdout="")

        with patch(
            "merlya.tools.security.config.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            checks, severity = await _check_ssh_config(mock_context, "web-01")

        assert checks == []
        assert severity == "info"


class TestFirewallAndUpdates:
    """Tests for firewall and auto-updates checks."""

    @pytest.mark.asyncio
    async def test_check_firewall_active(self, mock_context: MagicMock) -> None:
        mock_result = MagicMock(exit_code=0, stdout="Status: active")

        with patch(
            "merlya.tools.security.config.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            fw_check, severity = await _check_firewall(mock_context, "web-01")

        assert fw_check["value"] == "active"
        assert fw_check["status"] == "ok"
        assert severity == "info"

    @pytest.mark.asyncio
    async def test_check_firewall_inactive_sets_warning(self, mock_context: MagicMock) -> None:
        mock_result = MagicMock(exit_code=0, stdout="inactive")

        with patch(
            "merlya.tools.security.config.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            fw_check, severity = await _check_firewall(mock_context, "web-01")

        assert fw_check["value"] == "inactive"
        assert fw_check["status"] == "warning"
        assert severity == "warning"

    @pytest.mark.asyncio
    async def test_check_auto_updates_enabled(self, mock_context: MagicMock) -> None:
        mock_result = MagicMock(exit_code=0, stdout="enabled\n")

        with patch(
            "merlya.tools.security.config.execute_security_command",
            AsyncMock(return_value=mock_result),
        ):
            check = await _check_auto_updates(mock_context, "web-01")

        assert check["value"] == "enabled"
        assert check["status"] == "ok"


class TestCheckSecurityConfig:
    """Integration-ish test for top-level check_security_config."""

    @pytest.mark.asyncio
    async def test_aggregates_checks_and_severity(self, mock_context: MagicMock) -> None:
        with (
            patch(
                "merlya.tools.security.config._check_ssh_config",
                AsyncMock(return_value=([{"setting": "SSH", "status": "ok"}], "info")),
            ),
            patch(
                "merlya.tools.security.config._check_firewall",
                AsyncMock(return_value=({"setting": "Firewall", "status": "warning"}, "warning")),
            ),
            patch(
                "merlya.tools.security.config._check_auto_updates",
                AsyncMock(return_value={"setting": "Auto", "status": "ok"}),
            ),
        ):
            result = await check_security_config(mock_context, "web-01")

        assert result.success is True
        assert result.severity == "warning"
        assert len(result.data["checks"]) == 3
