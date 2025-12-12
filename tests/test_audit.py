"""Tests for audit logging module."""

from __future__ import annotations

import pytest

from merlya.audit.logger import AuditEvent, AuditEventType, AuditLogger


class TestAuditEvent:
    """Tests for AuditEvent."""

    def test_create_event(self) -> None:
        """Test creating an audit event."""
        event = AuditEvent(
            event_type=AuditEventType.COMMAND_EXECUTED,
            action="ssh_execute",
            target="web-01",
        )
        assert event.event_type == AuditEventType.COMMAND_EXECUTED
        assert event.action == "ssh_execute"
        assert event.target == "web-01"
        assert event.success is True
        assert event.event_id is not None

    def test_event_to_dict(self) -> None:
        """Test converting event to dictionary."""
        event = AuditEvent(
            event_type=AuditEventType.SKILL_INVOKED,
            action="disk_audit",
            target="web-01, web-02",
            details={"host_count": 2},
        )
        d = event.to_dict()
        assert d["event_type"] == "skill_invoked"
        assert d["action"] == "disk_audit"
        assert d["details"] == {"host_count": 2}

    def test_event_to_log_line(self) -> None:
        """Test formatting event as log line."""
        event = AuditEvent(
            event_type=AuditEventType.COMMAND_EXECUTED,
            action="uptime",
            target="web-01",
            success=True,
        )
        line = event.to_log_line()
        assert "command_executed" in line
        assert "OK" in line
        assert "uptime" in line
        assert "web-01" in line

    def test_failed_event_log_line(self) -> None:
        """Test formatting failed event."""
        event = AuditEvent(
            event_type=AuditEventType.DESTRUCTIVE_OPERATION,
            action="rm -rf",
            target="/var/log",
            success=False,
        )
        line = event.to_log_line()
        assert "FAIL" in line


class TestAuditLogger:
    """Tests for AuditLogger."""

    @pytest.fixture
    def logger(self) -> AuditLogger:
        """Create a test audit logger."""
        AuditLogger.reset_instance()
        return AuditLogger(enabled=True)

    @pytest.mark.asyncio
    async def test_log_disabled(self) -> None:
        """Test logging when disabled."""
        logger = AuditLogger(enabled=False)
        # Should not raise
        await logger.log(
            AuditEvent(
                event_type=AuditEventType.COMMAND_EXECUTED,
                action="test",
            )
        )

    @pytest.mark.asyncio
    async def test_log_command(self, logger: AuditLogger) -> None:
        """Test logging a command."""
        await logger.initialize()
        # Should not raise
        await logger.log_command(
            command="uptime",
            host="web-01",
            output="12:00:00 up 10 days",
            exit_code=0,
            success=True,
        )

    @pytest.mark.asyncio
    async def test_log_skill(self, logger: AuditLogger) -> None:
        """Test logging a skill invocation."""
        await logger.initialize()
        await logger.log_skill(
            skill_name="disk_audit",
            hosts=["web-01", "web-02"],
            task="check disk usage",
            success=True,
            duration_ms=1500,
        )

    @pytest.mark.asyncio
    async def test_log_tool(self, logger: AuditLogger) -> None:
        """Test logging tool usage."""
        await logger.initialize()
        await logger.log_tool(
            tool_name="ssh_execute",
            host="web-01",
            args={"command": "df -h"},
            success=True,
        )

    @pytest.mark.asyncio
    async def test_log_tool_sanitizes_sensitive(self, database) -> None:
        """Test that sensitive args are not logged."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)
        # This should not store password in details
        await logger.log_tool(
            tool_name="test",
            args={"command": "test", "password": "secret123"},
        )

        # Retrieve stored event and verify sanitization
        events = await logger.get_recent(limit=1)
        assert len(events) == 1
        event = events[0]
        details = event["details"]

        # Verify the raw secret is not present anywhere in details
        import json

        details_str = json.dumps(details)
        assert "secret123" not in details_str, "Raw secret should not be in stored details"

        # Verify password key exists but is redacted
        assert "args" in details
        assert "password" in details["args"]
        assert details["args"]["password"] == "[REDACTED]"

        # Verify non-sensitive args are preserved
        assert details["args"]["command"] == "test"

    @pytest.mark.asyncio
    async def test_log_destructive(self, logger: AuditLogger) -> None:
        """Test logging destructive operations."""
        await logger.initialize()
        # Request confirmation
        await logger.log_destructive(
            operation="delete",
            target="/var/log/old",
        )
        # Granted
        await logger.log_destructive(
            operation="delete",
            target="/var/log/old",
            confirmed=True,
            success=True,
        )
        # Denied
        await logger.log_destructive(
            operation="delete",
            target="/etc/passwd",
            confirmed=False,
            success=False,
        )

    @pytest.mark.asyncio
    async def test_singleton(self) -> None:
        """Test singleton pattern."""
        AuditLogger.reset_instance()
        logger1 = await AuditLogger.get_instance()
        logger2 = await AuditLogger.get_instance()
        assert logger1 is logger2

    @pytest.mark.asyncio
    async def test_get_audit_logger(self) -> None:
        """Test convenience function."""
        from merlya.audit import get_audit_logger

        AuditLogger.reset_instance()
        logger = await get_audit_logger()
        assert logger is not None
        assert isinstance(logger, AuditLogger)


class TestAuditLoggerWithDatabase:
    """Tests for AuditLogger with database persistence."""

    @pytest.mark.asyncio
    async def test_persist_and_retrieve(self, database) -> None:
        """Test persisting and retrieving audit logs."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)

        # Log some events
        await logger.log_command("ls -la", "web-01", success=True)
        await logger.log_skill("disk_audit", ["web-01"], task="check disk")

        # Retrieve
        events = await logger.get_recent(limit=10)
        assert len(events) == 2
        event_types = {e["event_type"] for e in events}
        assert "skill_invoked" in event_types
        assert "command_executed" in event_types

    @pytest.mark.asyncio
    async def test_filter_by_type(self, database) -> None:
        """Test filtering events by type."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)

        await logger.log_command("ls", "web-01")
        await logger.log_skill("test", ["web-01"])
        await logger.log_command("pwd", "web-02")

        # Filter by command
        events = await logger.get_recent(event_type=AuditEventType.COMMAND_EXECUTED)
        assert len(events) == 2
        assert all(e["event_type"] == "command_executed" for e in events)


class TestAuditLoggerLimitValidation:
    """Tests for limit validation in get_recent()."""

    @pytest.mark.asyncio
    async def test_get_recent_negative_limit_raises(self, database) -> None:
        """Test that negative limit raises ValueError."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)

        with pytest.raises(ValueError, match="limit must be at least 1"):
            await logger.get_recent(limit=-1)

    @pytest.mark.asyncio
    async def test_get_recent_zero_limit_raises(self, database) -> None:
        """Test that zero limit raises ValueError."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)

        with pytest.raises(ValueError, match="limit must be at least 1"):
            await logger.get_recent(limit=0)

    @pytest.mark.asyncio
    async def test_get_recent_excessive_limit_raises(self, database) -> None:
        """Test that excessive limit raises ValueError."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)

        with pytest.raises(ValueError, match="limit must be at most"):
            await logger.get_recent(limit=10000)

    @pytest.mark.asyncio
    async def test_get_recent_valid_limits(self, database) -> None:
        """Test that valid limits work correctly."""
        AuditLogger.reset_instance()
        logger = AuditLogger(enabled=True)
        await logger.initialize(db=database)

        # Valid limits should not raise
        await logger.get_recent(limit=1)
        await logger.get_recent(limit=50)
        await logger.get_recent(limit=1000)
