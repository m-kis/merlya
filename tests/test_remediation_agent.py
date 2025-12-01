"""
Tests for RemediationAgent with self-healing capabilities.
"""

import unittest
from unittest.mock import MagicMock, patch

from merlya.agents.remediation import (
    RemediationAgent,
    RemediationMode,
    RemediationResult,
    get_remediation_agent,
)


class TestRemediationMode(unittest.TestCase):
    """Test cases for RemediationMode enum."""

    def test_mode_values(self):
        """Test mode enum values."""
        self.assertEqual(RemediationMode.CONSERVATIVE.value, "conservative")
        self.assertEqual(RemediationMode.SEMI_AUTO.value, "semi_auto")
        self.assertEqual(RemediationMode.SENTINEL.value, "sentinel")


class TestRemediationAgent(unittest.TestCase):
    """Test cases for RemediationAgent."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_context = MagicMock()
        self.mock_context.get_context.return_value = {"local": {}}

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_init_default_mode(self, mock_km):
        """Test agent initializes with default conservative mode."""
        agent = RemediationAgent(self.mock_context)
        self.assertEqual(agent.mode, RemediationMode.CONSERVATIVE)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_init_custom_mode(self, mock_km):
        """Test agent initializes with custom mode."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.SENTINEL
        )
        self.assertEqual(agent.mode, RemediationMode.SENTINEL)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_set_mode(self, mock_km):
        """Test changing remediation mode."""
        agent = RemediationAgent(self.mock_context)
        agent.set_mode(RemediationMode.SEMI_AUTO)
        self.assertEqual(agent.mode, RemediationMode.SEMI_AUTO)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_assess_risk_high(self, mock_km):
        """Test high risk command detection."""
        agent = RemediationAgent(self.mock_context)

        high_risk_commands = [
            "rm -rf /",
            "dd if=/dev/zero of=/dev/sda",
            "DROP TABLE users",
            "shutdown now",
        ]

        for cmd in high_risk_commands:
            risk = agent._assess_risk(cmd)
            self.assertEqual(risk, "high", f"Expected high risk for: {cmd}")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_assess_risk_low(self, mock_km):
        """Test low risk command detection."""
        agent = RemediationAgent(self.mock_context)

        low_risk_commands = [
            "systemctl status nginx",
            "ps aux",
            "df -h",
            "docker ps",
            "kubectl get pods",
        ]

        for cmd in low_risk_commands:
            risk = agent._assess_risk(cmd)
            self.assertEqual(risk, "low", f"Expected low risk for: {cmd}")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_assess_risk_medium(self, mock_km):
        """Test medium risk command detection."""
        agent = RemediationAgent(self.mock_context)

        # Unknown commands default to medium
        risk = agent._assess_risk("some_unknown_command")
        self.assertEqual(risk, "medium")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_should_execute_conservative_denied(self, mock_km):
        """Test conservative mode blocks without approval."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.CONSERVATIVE,
            approval_callback=lambda x: False  # Always deny
        )

        action = {"command": "systemctl restart nginx", "risk_level": "medium"}
        should_exec, reason = agent._should_execute(action, force_confirm=False)

        self.assertFalse(should_exec)
        self.assertEqual(reason, "denied")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_should_execute_conservative_approved(self, mock_km):
        """Test conservative mode allows with approval."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.CONSERVATIVE,
            approval_callback=lambda x: True  # Always approve
        )

        action = {"command": "systemctl restart nginx", "risk_level": "medium"}
        should_exec, reason = agent._should_execute(action, force_confirm=False)

        self.assertTrue(should_exec)
        self.assertEqual(reason, "approved")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_should_execute_semi_auto_safe(self, mock_km):
        """Test semi-auto mode auto-executes safe commands."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.SEMI_AUTO,
        )

        action = {"command": "systemctl status nginx", "risk_level": "low"}
        should_exec, reason = agent._should_execute(action, force_confirm=False)

        self.assertTrue(should_exec)
        self.assertEqual(reason, "auto_safe")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_should_execute_semi_auto_risky(self, mock_km):
        """Test semi-auto mode asks for risky commands."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.SEMI_AUTO,
            approval_callback=lambda x: False  # Deny
        )

        action = {"command": "systemctl restart nginx", "risk_level": "medium"}
        should_exec, reason = agent._should_execute(action, force_confirm=False)

        self.assertFalse(should_exec)
        self.assertEqual(reason, "denied")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_should_execute_sentinel_auto(self, mock_km):
        """Test sentinel mode auto-executes medium risk."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.SENTINEL,
        )

        action = {"command": "systemctl restart nginx", "risk_level": "medium"}
        should_exec, reason = agent._should_execute(action, force_confirm=False)

        self.assertTrue(should_exec)
        self.assertEqual(reason, "auto_sentinel")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_should_execute_sentinel_high_risk(self, mock_km):
        """Test sentinel mode still asks for high risk."""
        agent = RemediationAgent(
            self.mock_context,
            mode=RemediationMode.SENTINEL,
            approval_callback=lambda x: False  # Deny
        )

        action = {"command": "rm -rf /tmp/*", "risk_level": "high"}
        should_exec, reason = agent._should_execute(action, force_confirm=False)

        self.assertFalse(should_exec)
        self.assertEqual(reason, "high_risk_denied")

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_dry_run(self, mock_km):
        """Test dry run returns plan without executing."""
        mock_km.return_value.get_remediation_for_incident.return_value = {
            "commands": ["systemctl status nginx"],
            "confidence": 0.8,
            "source": "pattern",
        }

        agent = RemediationAgent(self.mock_context)
        result = agent.run("Check nginx status", dry_run=True)

        self.assertTrue(result.success)
        self.assertEqual(len(result.actions_executed), 0)
        self.assertEqual(len(result.actions_skipped), 1)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_prepare_actions(self, mock_km):
        """Test action preparation with risk assessment."""
        agent = RemediationAgent(self.mock_context)

        remediation = {
            "commands": ["systemctl status nginx", "systemctl restart nginx"],
        }

        actions = agent._prepare_actions(remediation)

        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["risk_level"], "low")
        self.assertEqual(actions[1]["risk_level"], "medium")


class TestRemediationResult(unittest.TestCase):
    """Test cases for RemediationResult dataclass."""

    def test_result_creation(self):
        """Test result dataclass creation."""
        result = RemediationResult(
            success=True,
            mode=RemediationMode.CONSERVATIVE,
            actions_suggested=[{"command": "test"}],
            actions_executed=[{"command": "test", "result": {"success": True}}],
            actions_skipped=[],
            rollbacks_created=[],
            confidence=0.9,
            source="pattern",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.mode, RemediationMode.CONSERVATIVE)
        self.assertEqual(result.confidence, 0.9)
        self.assertIsNone(result.error)


class TestGetRemediationAgent(unittest.TestCase):
    """Test cases for get_remediation_agent factory."""

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_factory_conservative(self, mock_km):
        """Test factory with conservative mode."""
        mock_context = MagicMock()
        agent = get_remediation_agent(mock_context, mode="conservative")
        self.assertEqual(agent.mode, RemediationMode.CONSERVATIVE)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_factory_semi_auto(self, mock_km):
        """Test factory with semi-auto mode."""
        mock_context = MagicMock()
        agent = get_remediation_agent(mock_context, mode="semi_auto")
        self.assertEqual(agent.mode, RemediationMode.SEMI_AUTO)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_factory_sentinel(self, mock_km):
        """Test factory with sentinel mode."""
        mock_context = MagicMock()
        agent = get_remediation_agent(mock_context, mode="sentinel")
        self.assertEqual(agent.mode, RemediationMode.SENTINEL)

    @patch("merlya.agents.remediation.get_knowledge_manager")
    def test_factory_default(self, mock_km):
        """Test factory with unknown mode defaults to conservative."""
        mock_context = MagicMock()
        agent = get_remediation_agent(mock_context, mode="unknown")
        self.assertEqual(agent.mode, RemediationMode.CONSERVATIVE)


if __name__ == "__main__":
    unittest.main()
