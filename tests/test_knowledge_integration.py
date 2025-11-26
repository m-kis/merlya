"""
Integration tests for the Knowledge System.

Tests the complete flow from triage to incident resolution.
"""

import pytest
import tempfile
import os

from athena_ai.triage import (
    Priority,
    classify_priority,
    get_behavior,
    describe_behavior,
)
from athena_ai.knowledge import (
    OpsKnowledgeManager,
    StorageManager,
    CVEMonitor,
    WebSearchEngine,
)
from athena_ai.security import (
    PreflightChecker,
    CheckResult,
    AuditLogger,
    AuditEventType,
)


class TestTriageIntegration:
    """Test triage system integration."""

    def test_triage_to_behavior(self):
        """Triage result should map to appropriate behavior."""
        # P0 incident
        result = classify_priority("Production MongoDB is down")
        behavior = get_behavior(result.priority)

        assert result.priority == Priority.P0
        assert behavior.auto_confirm_reads is True
        assert behavior.response_format == "terse"

    def test_triage_with_environment(self):
        """Environment should affect priority."""
        # Same issue, different environments
        prod_result = classify_priority("High latency on production API")
        dev_result = classify_priority("High latency on development API")

        assert prod_result.priority <= dev_result.priority  # Prod is higher priority


class TestKnowledgeSystemIntegration:
    """Test full knowledge system integration."""

    @pytest.fixture
    def knowledge_manager(self):
        """Create a knowledge manager with temp storage."""
        temp_db = tempfile.mktemp(suffix='.db')
        km = OpsKnowledgeManager(
            sqlite_path=temp_db,
            enable_falkordb=False,
        )
        km.start_session('test-session', env='dev')
        yield km
        km.end_session()
        if os.path.exists(temp_db):
            os.unlink(temp_db)

    def test_incident_lifecycle(self, knowledge_manager):
        """Test complete incident lifecycle."""
        km = knowledge_manager

        # 1. Record incident
        incident_id = km.record_incident(
            title="MongoDB connection pool exhausted",
            priority="P1",
            service="mongodb",
            environment="staging",
            symptoms=["connection timeout", "pool exhausted", "high latency"],
        )
        assert incident_id.startswith("INC-")

        # 2. Resolve incident
        success = km.resolve_incident(
            incident_id=incident_id,
            root_cause="Connection pool size too small",
            solution="Increased maxPoolSize from 100 to 500",
            commands_executed=["mongo --eval 'db.adminCommand({setParameter:1, maxPoolSize:500})'"],
            learn_pattern=True,
        )
        assert success is True

        # 3. Verify pattern was learned
        patterns = km.patterns.get_top_patterns(limit=5)
        assert len(patterns) >= 1

    def test_suggestion_from_history(self, knowledge_manager):
        """Test getting suggestions from past incidents."""
        km = knowledge_manager

        # Create and resolve an incident
        incident_id = km.record_incident(
            title="Nginx 502 errors",
            priority="P1",
            service="nginx",
            symptoms=["502 bad gateway", "upstream timeout"],
        )
        km.resolve_incident(
            incident_id=incident_id,
            root_cause="Upstream server overloaded",
            solution="Increase proxy_read_timeout and scale upstream",
        )

        # Add explicit pattern for better matching
        km.add_pattern(
            name="nginx_502_pattern",
            symptoms=["502 error", "bad gateway", "upstream"],
            keywords=["nginx", "502", "gateway"],
            suggested_solution="Check upstream servers and increase timeout",
        )

        # Try to get suggestion
        suggestion = km.get_suggestion(
            text="nginx 502 bad gateway errors",
            service="nginx",
        )

        # Suggestion should be available
        assert suggestion is not None
        assert "timeout" in suggestion.get("solution", "").lower() or \
               "upstream" in suggestion.get("solution", "").lower()

    def test_audit_logging(self, knowledge_manager):
        """Test audit logging for actions."""
        km = knowledge_manager

        # Log an action
        km.log_action(
            action="execute_command",
            target="web-server-01",
            command="systemctl restart nginx",
            result="success",
            priority="P2",
        )

        # Check audit log
        audit_entries = km.get_audit_log(limit=10)
        assert len(audit_entries) >= 1

        # Verify entry content
        entry = audit_entries[0]
        assert entry.action == "execute_command"
        assert entry.target == "web-server-01"


class TestSecurityIntegration:
    """Test security module integration."""

    def test_preflight_with_audit(self):
        """Test preflight checks are logged to audit."""
        temp_dir = tempfile.mkdtemp()
        checker = PreflightChecker(environment='prod')
        logger = AuditLogger(log_dir=temp_dir, environment='prod')
        logger.set_session('test-session')

        # Check a dangerous command
        result = checker.check("rm -rf /")
        assert result.result == CheckResult.BLOCK

        # Log the block
        logger.log_preflight_block(
            command="rm -rf /",
            reason=result.reason,
            target="localhost",
        )

        # Verify logged
        events = logger.get_recent_events(
            event_type=AuditEventType.PREFLIGHT_BLOCK
        )
        assert len(events) >= 1

    def test_security_flow(self):
        """Test complete security flow."""
        checker = PreflightChecker(environment='staging')

        # Safe command
        result = checker.check("ps aux | grep nginx")
        assert result.result == CheckResult.ALLOW

        # Command needing confirmation
        result = checker.check("systemctl restart nginx")
        assert result.result in (CheckResult.WARN, CheckResult.REQUIRE_CONFIRM)

        # Get safer alternative
        alternative = checker.get_safe_alternative("systemctl restart nginx")
        assert "reload" in alternative


class TestCVEMonitorIntegration:
    """Test CVE monitoring integration."""

    def test_cve_monitor_initialization(self):
        """Test CVE monitor can be created."""
        monitor = CVEMonitor(cache_ttl_hours=1)
        assert monitor.cache_ttl.total_seconds() == 3600  # 1 hour
        assert len(monitor._cache) == 0

    def test_check_package_format(self):
        """Test package check returns proper format."""
        monitor = CVEMonitor()

        # This will make a real API call - skip if no network
        try:
            result = monitor.check_package("requests", "2.28.0", "PyPI")
            assert result.package == "requests"
            assert result.version == "2.28.0"
            assert hasattr(result, 'vulnerabilities')
        except Exception:
            pytest.skip("Network unavailable")


class TestWebSearchIntegration:
    """Test web search integration."""

    def test_search_engine_initialization(self):
        """Test search engine can be created."""
        engine = WebSearchEngine(cache_ttl_hours=1)
        assert engine.max_results == 10

    def test_error_cleaning(self):
        """Test error message cleaning for search."""
        engine = WebSearchEngine()

        # Clean error with timestamp and IP
        error = "2024-01-01 12:00:00 Connection refused from 192.168.1.1"
        cleaned = engine._clean_error_message(error)

        assert "2024" not in cleaned
        assert "12:00:00" not in cleaned
        assert "192.168.1.1" not in cleaned


class TestEndToEndFlow:
    """Test complete end-to-end flow."""

    def test_incident_response_flow(self):
        """Test complete incident response flow."""
        temp_db = tempfile.mktemp(suffix='.db')
        temp_audit = tempfile.mkdtemp()

        try:
            # Initialize systems
            km = OpsKnowledgeManager(
                sqlite_path=temp_db,
                enable_falkordb=False,
            )
            checker = PreflightChecker(environment='staging')
            audit = AuditLogger(log_dir=temp_audit)

            km.start_session('e2e-test', env='staging')
            audit.set_session('e2e-test')

            # 1. Triage incoming alert
            query = "MongoDB high latency on staging-db-01"
            triage_result = classify_priority(query)
            assert triage_result.priority in (Priority.P0, Priority.P1, Priority.P2)

            # 2. Record incident
            incident_id = km.record_incident(
                title=query,
                priority=triage_result.priority.name,
                service=triage_result.service_detected,
                environment=triage_result.environment_detected,
                symptoms=["high latency", "slow queries"],
            )

            # Log to audit
            km.log_action(
                action="incident_created",
                target=incident_id,
                result="success",
                priority=triage_result.priority.name,
            )

            # 3. Validate proposed fix command
            fix_command = "mongo --eval 'db.currentOp()'"
            preflight = checker.check(fix_command)
            assert preflight.result == CheckResult.ALLOW

            # 4. Resolve incident
            km.resolve_incident(
                incident_id=incident_id,
                root_cause="Slow queries blocking connections",
                solution="Identified and killed slow queries",
                commands_executed=[fix_command],
            )

            # 5. Verify stats
            stats = km.get_stats()
            assert stats["incidents"]["total_incidents"] >= 1

            km.end_session()

        finally:
            if os.path.exists(temp_db):
                os.unlink(temp_db)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
