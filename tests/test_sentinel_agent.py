"""
Tests for SentinelAgent proactive monitoring system.
"""

import unittest
from unittest.mock import MagicMock, patch

from athena_ai.agents.sentinel import (
    Alert,
    AlertSeverity,
    CheckResult,
    HealthCheck,
    SentinelAgent,
    SentinelStatus,
    get_sentinel_agent,
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
        import athena_ai.agents.sentinel as module
        module._sentinel_instance = None

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_init_default(self, mock_km):
        """Test agent initialization with defaults."""
        agent = SentinelAgent()

        self.assertEqual(agent.status, SentinelStatus.STOPPED)
        self.assertFalse(agent.auto_remediate)
        self.assertEqual(len(agent._checks), 0)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_add_check(self, mock_km):
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
        self.assertEqual(agent._failure_counts["test-ping"], 0)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_remove_check(self, mock_km):
        """Test removing a health check."""
        agent = SentinelAgent()
        check = HealthCheck(name="to-remove", target="localhost", check_type="ping")
        agent.add_check(check)

        result = agent.remove_check("to-remove")

        self.assertTrue(result)
        self.assertNotIn("to-remove", agent._checks)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_remove_nonexistent_check(self, mock_km):
        """Test removing non-existent check."""
        agent = SentinelAgent()

        result = agent.remove_check("nonexistent")

        self.assertFalse(result)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_enable_disable_check(self, mock_km):
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

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_list_checks(self, mock_km):
        """Test listing checks."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="check1", target="host1", check_type="ping"))
        agent.add_check(HealthCheck(name="check2", target="host2", check_type="port"))

        checks = agent.list_checks()

        self.assertEqual(len(checks), 2)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_start_without_checks(self, mock_km):
        """Test starting without any checks configured."""
        agent = SentinelAgent()

        result = agent.start()

        self.assertFalse(result)
        self.assertEqual(agent.status, SentinelStatus.STOPPED)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_start_with_checks(self, mock_km):
        """Test starting with checks configured."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))

        result = agent.start()

        self.assertTrue(result)
        self.assertEqual(agent.status, SentinelStatus.RUNNING)

        # Cleanup
        agent.stop()

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_start_already_running(self, mock_km):
        """Test starting when already running."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))
        agent.start()

        result = agent.start()

        self.assertFalse(result)

        # Cleanup
        agent.stop()

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_stop(self, mock_km):
        """Test stopping the agent."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))
        agent.start()

        result = agent.stop()

        self.assertTrue(result)
        self.assertEqual(agent.status, SentinelStatus.STOPPED)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_pause_resume(self, mock_km):
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

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_get_status(self, mock_km):
        """Test getting agent status."""
        agent = SentinelAgent()
        agent.add_check(HealthCheck(name="test", target="localhost", check_type="ping"))

        status = agent.get_status()

        self.assertEqual(status["status"], "stopped")
        self.assertEqual(status["checks_configured"], 1)
        self.assertEqual(status["active_alerts"], 0)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_check_ping_success(self, mock_km):
        """Test ping check execution."""
        agent = SentinelAgent()
        check = HealthCheck(name="ping-test", target="127.0.0.1", check_type="ping")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success, details = agent._check_ping(check)

            self.assertTrue(success)
            self.assertEqual(details["exit_code"], 0)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_check_ping_failure(self, mock_km):
        """Test ping check failure."""
        agent = SentinelAgent()
        check = HealthCheck(name="ping-test", target="invalid-host", check_type="ping")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            success, details = agent._check_ping(check)

            self.assertFalse(success)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_check_port_success(self, mock_km):
        """Test port check with mock."""
        agent = SentinelAgent()
        check = HealthCheck(
            name="port-test",
            target="localhost",
            check_type="port",
            parameters={"port": 22}
        )

        with patch("socket.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_socket.return_value = mock_sock

            success, details = agent._check_port(check)

            self.assertTrue(success)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_check_http_success(self, mock_km):
        """Test HTTP check with mock."""
        agent = SentinelAgent()
        check = HealthCheck(
            name="http-test",
            target="localhost",
            check_type="http",
            parameters={"url": "http://localhost/health", "expected_status": 200}
        )

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            success, details = agent._check_http(check)

            self.assertTrue(success)
            self.assertEqual(details["status"], 200)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_process_result_success(self, mock_km):
        """Test processing successful check result."""
        agent = SentinelAgent()
        check = HealthCheck(name="test", target="localhost", check_type="ping")
        agent.add_check(check)
        agent._failure_counts["test"] = 5  # Simulate previous failures

        result = CheckResult(
            check=check,
            success=True,
            response_time_ms=10.0,
            timestamp="2024-01-01T00:00:00",
        )

        agent._process_result(result)

        # Failure count should reset
        self.assertEqual(agent._failure_counts["test"], 0)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_process_result_failure(self, mock_km):
        """Test processing failed check result."""
        agent = SentinelAgent()
        check = HealthCheck(name="test", target="localhost", check_type="ping")
        agent.add_check(check)

        result = CheckResult(
            check=check,
            success=False,
            response_time_ms=0,
            timestamp="2024-01-01T00:00:00",
            error="Connection refused",
        )

        agent._process_result(result)

        self.assertEqual(agent._failure_counts["test"], 1)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_alert_creation(self, mock_km):
        """Test alert creation after threshold failures."""
        alerts_received = []

        def capture_alert(alert):
            alerts_received.append(alert)

        agent = SentinelAgent(alert_callback=capture_alert)
        check = HealthCheck(
            name="alert-test",
            target="localhost",
            check_type="ping",
            threshold_failures=2,
        )
        agent.add_check(check)

        result = CheckResult(
            check=check,
            success=False,
            response_time_ms=0,
            timestamp="2024-01-01T00:00:00",
            error="Connection refused",
        )

        # First failure - no alert yet
        agent._process_result(result)
        self.assertEqual(len(alerts_received), 0)

        # Second failure - threshold reached, alert created
        agent._process_result(result)
        self.assertEqual(len(alerts_received), 1)
        self.assertEqual(alerts_received[0].severity, AlertSeverity.INFO)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_acknowledge_alert(self, mock_km):
        """Test acknowledging an alert."""
        agent = SentinelAgent()
        agent._alerts["test"] = Alert(
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
        self.assertTrue(agent._alerts["test"].acknowledged)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_get_alerts(self, mock_km):
        """Test getting active alerts."""
        agent = SentinelAgent()
        agent._alerts["active"] = Alert(
            id="alert_1",
            check_name="active",
            target="host1",
            severity=AlertSeverity.CRITICAL,
            message="Active alert",
            timestamp="2024-01-01T00:00:00",
            consecutive_failures=5,
        )
        agent._alerts["acked"] = Alert(
            id="alert_2",
            check_name="acked",
            target="host2",
            severity=AlertSeverity.WARNING,
            message="Acknowledged alert",
            timestamp="2024-01-01T00:00:00",
            consecutive_failures=3,
            acknowledged=True,
        )

        # Without acknowledged
        alerts = agent.get_alerts(include_acknowledged=False)
        self.assertEqual(len(alerts), 1)

        # With acknowledged
        alerts = agent.get_alerts(include_acknowledged=True)
        self.assertEqual(len(alerts), 2)


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
        import athena_ai.agents.sentinel as module
        module._sentinel_instance = None

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_singleton(self, mock_km):
        """Test factory returns singleton."""
        agent1 = get_sentinel_agent()
        agent2 = get_sentinel_agent()

        self.assertIs(agent1, agent2)

    @patch("athena_ai.agents.sentinel.get_knowledge_manager")
    def test_factory_with_options(self, mock_km):
        """Test factory with custom options."""
        mock_executor = MagicMock()
        agent = get_sentinel_agent(
            executor=mock_executor,
            auto_remediate=True,
        )

        self.assertTrue(agent.auto_remediate)


if __name__ == "__main__":
    unittest.main()
