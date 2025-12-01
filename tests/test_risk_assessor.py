"""
Tests for RiskAssessor - command risk classification.
"""
import pytest


class TestRiskAssessor:
    """Test RiskAssessor class."""

    @pytest.fixture
    def assessor(self):
        from merlya.security.risk_assessor import RiskAssessor
        return RiskAssessor()

    def test_low_risk_commands(self, assessor):
        """Should classify read-only commands as low risk."""
        low_risk_commands = [
            "systemctl status nginx",
            "ps aux",
            "df -h",
            "cat /etc/hosts",
            "ls -la",
            "grep error /var/log/syslog",
            "uname -a",
            "hostname",
            "uptime",
            "free -m",
        ]

        for cmd in low_risk_commands:
            result = assessor.assess(cmd)
            assert result["level"] == "low", f"Expected low risk for: {cmd}"

    def test_moderate_risk_commands(self, assessor):
        """Should classify configuration commands as moderate risk."""
        moderate_commands = [
            "systemctl reload nginx",
            "chmod 755 /var/www",
            "chown www-data:www-data /var/www",
            "touch /tmp/test",
            "mkdir /tmp/newdir",
        ]

        for cmd in moderate_commands:
            result = assessor.assess(cmd)
            assert result["level"] == "moderate", f"Expected moderate risk for: {cmd}"

    def test_critical_risk_commands(self, assessor):
        """Should classify dangerous commands as critical risk."""
        critical_commands = [
            "systemctl restart nginx",
            "systemctl stop mongodb",
            "rm -rf /tmp/test",
            "iptables -F",
            "shutdown -h now",
            "reboot",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sdb1",
        ]

        for cmd in critical_commands:
            result = assessor.assess(cmd)
            assert result["level"] == "critical", f"Expected critical risk for: {cmd}"

    def test_empty_command(self, assessor):
        """Should handle empty command gracefully."""
        result = assessor.assess("")
        assert result["level"] == "low"
        assert "Empty" in result["reason"]

    def test_whitespace_only_command(self, assessor):
        """Should handle whitespace-only command."""
        result = assessor.assess("   ")
        assert result["level"] == "low"
        assert "Empty" in result["reason"]

    def test_none_command(self, assessor):
        """Should handle None command."""
        result = assessor.assess(None)
        assert result["level"] == "low"

    def test_unknown_command_defaults_moderate(self, assessor):
        """Should default to moderate for unknown commands."""
        result = assessor.assess("custom-unknown-tool --do-something")
        assert result["level"] == "moderate"
        assert "Unknown" in result["reason"]

    def test_reason_contains_pattern(self, assessor):
        """Should include matched pattern in reason."""
        result = assessor.assess("systemctl restart nginx")
        assert "systemctl restart" in result["reason"]


class TestRequiresConfirmation:
    """Test requires_confirmation method."""

    @pytest.fixture
    def assessor(self):
        from merlya.security.risk_assessor import RiskAssessor
        return RiskAssessor()

    def test_low_risk_no_confirmation(self, assessor):
        """Low risk should not require confirmation."""
        assert assessor.requires_confirmation("low") is False

    def test_moderate_risk_requires_confirmation(self, assessor):
        """Moderate risk should require confirmation."""
        assert assessor.requires_confirmation("moderate") is True

    def test_critical_risk_requires_confirmation(self, assessor):
        """Critical risk should require confirmation."""
        assert assessor.requires_confirmation("critical") is True


class TestRiskLevels:
    """Test RISK_LEVELS classification."""

    def test_risk_levels_structure(self):
        """Should have correct risk levels structure."""
        from merlya.security.risk_assessor import RiskAssessor

        assessor = RiskAssessor()
        assert "low" in assessor.RISK_LEVELS
        assert "moderate" in assessor.RISK_LEVELS
        assert "critical" in assessor.RISK_LEVELS

    def test_risk_levels_not_empty(self):
        """Each risk level should have patterns."""
        from merlya.security.risk_assessor import RiskAssessor

        assessor = RiskAssessor()
        for level, patterns in assessor.RISK_LEVELS.items():
            assert len(patterns) > 0, f"No patterns for {level} risk"
