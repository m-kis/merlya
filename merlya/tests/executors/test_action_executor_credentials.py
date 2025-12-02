import unittest
from unittest.mock import MagicMock, patch

from merlya.executors.action_executor import ActionExecutor
from merlya.triage.error_analyzer import ErrorAnalysis, ErrorType

class TestActionExecutorCredentials(unittest.TestCase):
    def setUp(self):
        self.mock_credentials = MagicMock()
        # Test interactive mode (the old behavior)
        self.executor = ActionExecutor(
            credential_manager=self.mock_credentials,
            interactive=True
        )

        # Mock risk assessor to always allow execution
        self.executor.risk_assessor.assess = MagicMock(return_value={"level": "low"})
        self.executor.risk_assessor.requires_confirmation = MagicMock(return_value=False)

    @patch("merlya.executors.action_executor.redact_sensitive_info")
    def test_execute_retry_on_credential_error(self, mock_redact):
        """Test that execute retries when a credential error occurs."""
        mock_redact.side_effect = lambda x: x
        target = "remote-host"
        command = "mongo --eval 'db.stats()'"
        
        # Mock _execute_remote to fail first, then succeed
        # First failure result
        fail_result = {
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Authentication failed.",
            "error_analysis": {
                "type": "credential",
                "confidence": 0.9,
                "needs_credentials": True,
                "suggested_action": "Provide credentials",
                "matched_pattern": "Authentication failed"
            }
        }
        
        # Second success result
        success_result = {
            "success": True,
            "exit_code": 0,
            "stdout": "Stats: ...",
            "stderr": "",
            "duration_ms": 100
        }
        
        self.executor._execute_remote = MagicMock(side_effect=[fail_result, success_result])
        
        # Mock prompt_credentials to return valid credentials
        self.executor.prompt_credentials = MagicMock(return_value=("user", "pass"))
        
        # Execute
        result = self.executor.execute(target, command)
        
        # Verify
        self.assertTrue(result["success"])
        self.assertEqual(self.executor._execute_remote.call_count, 2)
        self.executor.prompt_credentials.assert_called_once()
        
    @patch("merlya.executors.action_executor.redact_sensitive_info")
    def test_execute_no_retry_if_credentials_cancelled(self, mock_redact):
        """Test that execute stops retrying if credential prompt is cancelled."""
        mock_redact.side_effect = lambda x: x
        target = "remote-host"
        command = "mongo --eval 'db.stats()'"
        
        fail_result = {
            "success": False,
            "exit_code": 1,
            "stderr": "Authentication failed.",
            "error_analysis": {
                "type": "credential",
                "confidence": 0.9,
                "needs_credentials": True
            }
        }
        
        self.executor._execute_remote = MagicMock(return_value=fail_result)
        
        # Mock prompt_credentials to return None (cancelled)
        self.executor.prompt_credentials = MagicMock(return_value=None)
        
        # Execute
        result = self.executor.execute(target, command)
        
        # Verify
        self.assertFalse(result["success"])
        self.assertEqual(self.executor._execute_remote.call_count, 1) # Should stop after 1st attempt and prompt
        self.executor.prompt_credentials.assert_called_once()

class TestActionExecutorNonInteractive(unittest.TestCase):
    """Tests for non-interactive mode (agent context)."""

    def setUp(self):
        self.mock_credentials = MagicMock()
        # Test non-interactive mode (default for agent context)
        self.executor = ActionExecutor(
            credential_manager=self.mock_credentials,
            interactive=False  # Default
        )

        # Mock risk assessor to always allow execution
        self.executor.risk_assessor.assess = MagicMock(return_value={"level": "low"})
        self.executor.risk_assessor.requires_confirmation = MagicMock(return_value=False)

    @patch("merlya.executors.action_executor.redact_sensitive_info")
    def test_non_interactive_returns_error_without_blocking(self, mock_redact):
        """Test that non-interactive mode returns error immediately without blocking."""
        mock_redact.side_effect = lambda x: x
        target = "remote-host"
        command = "mongo --eval 'db.stats()'"

        # Failure result with credential error
        fail_result = {
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Authentication failed.",
            "error_analysis": {
                "type": "credential",
                "confidence": 0.9,
                "needs_credentials": True,
                "suggested_action": "Provide credentials",
                "matched_pattern": "Authentication failed"
            }
        }

        self.executor._execute_remote = MagicMock(return_value=fail_result)

        # Execute - should NOT block and should NOT call prompt_credentials
        result = self.executor.execute(target, command)

        # Verify
        self.assertFalse(result["success"])
        self.assertTrue(result["error_analysis"]["needs_credentials"])
        self.assertEqual(self.executor._execute_remote.call_count, 1)  # Only one attempt
        # prompt_credentials should NOT be called in non-interactive mode
        self.mock_credentials.get_db_credentials.assert_not_called()

    @patch("merlya.executors.action_executor.redact_sensitive_info")
    def test_non_interactive_success_returns_normally(self, mock_redact):
        """Test that non-interactive mode returns success normally."""
        mock_redact.side_effect = lambda x: x
        target = "remote-host"
        command = "ls -la"

        success_result = {
            "success": True,
            "exit_code": 0,
            "stdout": "file1.txt\nfile2.txt",
            "stderr": "",
            "duration_ms": 50
        }

        self.executor._execute_remote = MagicMock(return_value=success_result)

        result = self.executor.execute(target, command)

        self.assertTrue(result["success"])
        self.assertEqual(result["stdout"], "file1.txt\nfile2.txt")

    @patch("merlya.executors.action_executor.redact_sensitive_info")
    def test_non_interactive_permission_error_without_credentials(self, mock_redact):
        """Test that permission errors without needs_credentials flag are returned."""
        mock_redact.side_effect = lambda x: x
        target = "remote-host"
        command = "cat /etc/shadow"

        # Permission error (not credential)
        fail_result = {
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Permission denied",
            "error_analysis": {
                "type": "permission",
                "confidence": 0.85,
                "needs_credentials": False,  # Not a credential issue
                "suggested_action": "Use elevated privileges"
            }
        }

        self.executor._execute_remote = MagicMock(return_value=fail_result)

        result = self.executor.execute(target, command)

        self.assertFalse(result["success"])
        self.assertFalse(result["error_analysis"]["needs_credentials"])
        self.assertEqual(result["error_analysis"]["type"], "permission")


if __name__ == "__main__":
    unittest.main()
