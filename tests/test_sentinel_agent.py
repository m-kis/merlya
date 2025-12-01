"""
Tests for SentinelAgent proactive monitoring system.
"""

import unittest
from unittest.mock import MagicMock

from merlya.agents.sentinel import (
    SentinelAgent,
    get_sentinel_agent,
)
from merlya.agents.sentinel_service.models import (
    Alert,
    AlertSeverity,
    HealthCheck,
    SentinelStatus,
)


class TestHealthCheck(unittest.TestCase):
    """Test cases for HealthCheck dataclass."""

    def test_health_check_defaults(self):
        """Test health check default values."""
        check = HealthCheck(
            name="test-check",
            target="localhost",
            check_type="ping",
        )

        self.assertEqual(check.interval_seconds, 60)
        self.assertEqual(check.timeout_seconds, 10)
        self.assertEqual(check.threshold_failures, 3)
        self.assertTrue(check.enabled)

    def test_health_check_custom(self):
        """Test health check with custom values."""
        check = HealthCheck(
            name="custom-check",
            target="web-server",
            check_type="http",
            interval_seconds=30,
            timeout_seconds=5,
            threshold_failures=5,
            parameters={"url": "http://web-server/health"},
        )

        self.assertEqual(check.interval_seconds, 30)
        self.assertEqual(check.parameters["url"], "http://web-server/health")


class TestSentinelAgent(unittest.TestCase):
    """Test cases for SentinelAgent."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset singleton for each test
        import merlya.agents.sentinel as module
        module._sentinel_instance = None

    def test_init_default(self):
        """Test agent initialization with defaults."""
        agent = SentinelAgent()

        self.assertEqual(agent.status, SentinelStatus.STOPPED)
        self.assertEqual(len(agent._checks), 0)

    def test_add_check(self):
        """Test adding a health check."""
        agent = SentinelAgent()
        check = HealthCheck(
            name="test-ping",
            target="localhost",
            check_type="ping",
        )

        result = agent.add_check(check)

        self.assertTrue(result)
        self.assertIn("test-ping", agent._checks)

    def test_remove_check(self):
        """Test removing a health check."""
        agent = SentinelAgent()
        check = HealthCheck(name="to-remove", target="localhost", check_type="ping")
        agent.add_check(check)

        result = agent.remove_check("to-remove")

        self.assertTrue(result)
        self.assertNotIn("to-remove", agent._checks)

    def test_remove_nonexistent_check(self):
        """Test removing non-existent check."""
        agent = SentinelAgent()

        result = agent.remove_check("nonexistent")

        self.assertFalse(result)

    def test_enable_disable_check(self):
        """Test enabling and disabling checks."""
        agent = SentinelAgent()
        check = HealthCheck(name="toggle", target="localhost", check_type="ping")
        agent.add_check(check)

        # Disable
        agent.disable_check("toggle")
        self.assertFalse(agent._checks["toggle"].enabled)

        # Enable
        agent.enable_check("toggle")
        self.assertTrue(agent._checks["toggle"].enabled)

    def test_list_checks(self):
        """Test listing checks."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="check1", target="host1", check_type="ping"))
        agent.add_check(HealthCheck(name="check2", target="host2", check_type="port"))

        checks = agent.list_checks()

        self.assertEqual(len(checks), 2)

    def test_start_without_checks(self):
        """Test starting without any checks configured."""
        agent = SentinelAgent()

        result = agent.start()

        self.assertFalse(result)
        self.assertEqual(agent.status, SentinelStatus.STOPPED)

    def test_start_with_checks(self):
        """Test starting with checks configured."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))

        result = agent.start()

        self.assertTrue(result)
        self.assertEqual(agent.status, SentinelStatus.RUNNING)

        # Cleanup
        agent.stop()

    def test_start_already_running(self):
        """Test starting when already running."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))
        agent.start()

        result = agent.start()

        self.assertFalse(result)

        # Cleanup
        agent.stop()

    def test_stop(self):
        """Test stopping the agent."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))
        agent.start()

        result = agent.stop()

        self.assertTrue(result)
        self.assertEqual(agent.status, SentinelStatus.STOPPED)

    def test_pause_resume(self):
        """Test pausing and resuming."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))
        agent.start()

        # Pause
        result = agent.pause()
        self.assertTrue(result)
        self.assertEqual(agent.status, SentinelStatus.PAUSED)

        # Resume
        result = agent.resume()
        self.assertTrue(result)
        self.assertEqual(agent.status, SentinelStatus.RUNNING)

        # Cleanup
        agent.stop()

    def test_get_status(self):
        """Test getting agent status."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))

        status = agent.get_status()

        self.assertEqual(status["status"], "stopped")
        self.assertEqual(status["checks_configured"], 1)
        self.assertEqual(status["active_alerts"], 0)

    def test_get_alerts(self):
        """Test getting alerts delegates to alert_manager."""
        agent = SentinelAgent()

        alerts = agent.get_alerts()

        self.assertEqual(len(alerts), 0)

    def test_acknowledge_alert(self):
        """Test acknowledging alert delegates to alert_manager."""
        agent = SentinelAgent()
        # Add a mock alert to the manager
        agent.alert_manager._alerts["test"] = Alert(
            id="alert_1",
            check_name="test",
            target="localhost",
            severity=AlertSeverity.WARNING,
            message="Test alert",
            timestamp="2024-01-01T00:00:00",
            consecutive_failures=3,
        )

        result = agent.acknowledge_alert("test")

        self.assertTrue(result)


class TestAlertSeverity(unittest.TestCase):
    """Test cases for AlertSeverity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        self.assertEqual(AlertSeverity.INFO.value, "info")
        self.assertEqual(AlertSeverity.WARNING.value, "warning")
        self.assertEqual(AlertSeverity.CRITICAL.value, "critical")


class TestGetSentinelAgent(unittest.TestCase):
    """Test cases for get_sentinel_agent factory."""

    def setUp(self):
        """Reset singleton for each test."""
        import merlya.agents.sentinel as module
        module._sentinel_instance = None

    def test_singleton(self):
        """Test factory returns singleton."""
        agent1 = get_sentinel_agent()
        agent2 = get_sentinel_agent()

        self.assertIs(agent1, agent2)

    def test_factory_with_options(self):
        """Test factory with custom options."""
        mock_executor = MagicMock()
        agent = get_sentinel_agent(
            executor=mock_executor,
            auto_remediate=True,
        )

        # Verify agent was created (auto_remediate is passed to AlertManager)
        self.assertIsNotNone(agent)


if __name__ == "__main__":
    unittest.main()
