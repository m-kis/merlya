"""Tests for centers base classes."""

from datetime import UTC, datetime

from merlya.centers.base import (
    CenterDeps,
    CenterMode,
    CenterResult,
    Evidence,
    RiskLevel,
)


class TestCenterMode:
    """Tests for CenterMode enum."""

    def test_diagnostic_mode(self) -> None:
        """Test diagnostic mode value."""
        assert CenterMode.DIAGNOSTIC.value == "diagnostic"

    def test_change_mode(self) -> None:
        """Test change mode value."""
        assert CenterMode.CHANGE.value == "change"

    def test_from_string(self) -> None:
        """Test creating mode from string."""
        assert CenterMode("diagnostic") == CenterMode.DIAGNOSTIC
        assert CenterMode("change") == CenterMode.CHANGE


class TestRiskLevel:
    """Tests for RiskLevel enum."""

    def test_risk_levels_ordered(self) -> None:
        """Test risk levels are defined correctly."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"


class TestCenterDeps:
    """Tests for CenterDeps model."""

    def test_create_minimal_deps(self) -> None:
        """Test creating deps with minimal info."""
        deps = CenterDeps(target="web-01", task="check disk usage")
        assert deps.target == "web-01"
        assert deps.task == "check disk usage"
        assert deps.host is None
        assert deps.extra == {}

    def test_create_deps_with_extra(self) -> None:
        """Test creating deps with extra data."""
        deps = CenterDeps(
            target="db-01",
            task="restart service",
            extra={"service": "postgresql"},
        )
        assert deps.extra["service"] == "postgresql"


class TestEvidence:
    """Tests for Evidence model."""

    def test_create_evidence(self) -> None:
        """Test creating evidence."""
        evidence = Evidence(
            host="web-01",
            command="df -h",
            output="/dev/sda1 100G 50G 50G 50%",
            exit_code=0,
            duration_ms=150,
        )
        assert evidence.host == "web-01"
        assert evidence.command == "df -h"
        assert evidence.exit_code == 0
        assert evidence.duration_ms == 150
        assert evidence.timestamp is not None

    def test_evidence_has_timestamp(self) -> None:
        """Test evidence has automatic timestamp."""
        before = datetime.now(UTC)
        evidence = Evidence(
            host="test",
            command="echo",
            output="",
            exit_code=0,
            duration_ms=0,
        )
        after = datetime.now(UTC)
        assert before <= evidence.timestamp <= after


class TestCenterResult:
    """Tests for CenterResult model."""

    def test_create_success_result(self) -> None:
        """Test creating a successful result."""
        result = CenterResult(
            success=True,
            message="Operation completed",
            mode=CenterMode.DIAGNOSTIC,
        )
        assert result.success is True
        assert result.mode == CenterMode.DIAGNOSTIC
        assert result.evidence == []
        assert result.applied is False

    def test_create_change_result(self) -> None:
        """Test creating a change result."""
        result = CenterResult(
            success=True,
            message="Service restarted",
            mode=CenterMode.CHANGE,
            applied=True,
            rollback_available=True,
            post_check_passed=True,
        )
        assert result.mode == CenterMode.CHANGE
        assert result.applied is True
        assert result.rollback_available is True
        assert result.post_check_passed is True

    def test_result_with_evidence(self) -> None:
        """Test result with evidence attached."""
        evidence = Evidence(
            host="web-01",
            command="uptime",
            output="up 10 days",
            exit_code=0,
            duration_ms=100,
        )
        result = CenterResult(
            success=True,
            message="Collected info",
            mode=CenterMode.DIAGNOSTIC,
            evidence=[evidence],
        )
        assert len(result.evidence) == 1
        assert result.evidence[0].command == "uptime"

    def test_result_with_data(self) -> None:
        """Test result with additional data."""
        result = CenterResult(
            success=True,
            message="Found issues",
            mode=CenterMode.DIAGNOSTIC,
            data={"disk_usage": 85, "alerts": ["high disk"]},
        )
        assert result.data["disk_usage"] == 85
        assert "high disk" in result.data["alerts"]
