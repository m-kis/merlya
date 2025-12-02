"""Tests for request_credentials tool."""
import unittest
from unittest.mock import MagicMock, patch


class TestRequestCredentials(unittest.TestCase):
    """Tests for the request_credentials tool."""

    def setUp(self):
        # Reset the tool context before each test
        from merlya.tools import base
        base._tool_context = None

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_declined(self, mock_get_ctx):
        """Test that declining credential request returns appropriate message."""
        from merlya.tools.interaction import request_credentials

        # Setup mock context
        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.console = MagicMock()
        mock_ctx.get_user_input = MagicMock(return_value="no")
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed",
            reason="Database access required"
        )

        self.assertIn("declined", result.lower())
        mock_ctx.credentials._cache_credential.assert_not_called()

    @patch("merlya.tools.interaction.get_tool_context")
    @patch("getpass.getpass")
    def test_request_credentials_accepted(self, mock_getpass, mock_get_ctx):
        """Test that accepting credential request stores credentials."""
        from merlya.tools.interaction import request_credentials

        # Setup mock context
        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.credentials._cache_credential_tuple = MagicMock()
        mock_ctx.credentials.set_secret = MagicMock()
        mock_ctx.console = MagicMock()
        # First call: accept (yes), Second call: username
        mock_ctx.get_user_input = MagicMock(side_effect=["yes", "admin"])
        mock_get_ctx.return_value = mock_ctx

        # Mock getpass for password
        mock_getpass.return_value = "secret123"

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed"
        )

        self.assertIn("stored successfully", result.lower())
        mock_ctx.credentials._cache_credential_tuple.assert_called_once()
        # Check that secrets were set
        self.assertEqual(mock_ctx.credentials.set_secret.call_count, 2)

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_keyboard_interrupt(self, mock_get_ctx):
        """Test that keyboard interrupt cancels gracefully."""
        from merlya.tools.interaction import request_credentials

        # Setup mock context
        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.console = MagicMock()
        mock_ctx.get_user_input = MagicMock(side_effect=KeyboardInterrupt)
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed"
        )

        self.assertIn("cancelled", result.lower())

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_empty_username(self, mock_get_ctx):
        """Test that empty username is rejected."""
        from merlya.tools.interaction import request_credentials

        # Setup mock context
        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.console = MagicMock()
        # First call: accept (yes), Second call: empty username
        mock_ctx.get_user_input = MagicMock(side_effect=["yes", ""])
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed"
        )

        self.assertIn("cannot be empty", result.lower())

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_no_credential_manager(self, mock_get_ctx):
        """Test handling when credential manager is not available."""
        from merlya.tools.interaction import request_credentials

        # Setup mock context without credentials
        mock_ctx = MagicMock()
        mock_ctx.credentials = None
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed"
        )

        self.assertIn("not available", result.lower())

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_invalid_username_characters(self, mock_get_ctx):
        """Test that invalid characters in username are rejected."""
        from merlya.tools.interaction import request_credentials

        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.console = MagicMock()
        # Accept, then provide username with shell metacharacters
        mock_ctx.get_user_input = MagicMock(side_effect=["yes", "user;rm -rf /"])
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed"
        )

        self.assertIn("invalid characters", result.lower())

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_username_too_long(self, mock_get_ctx):
        """Test that too long username is rejected."""
        from merlya.tools.interaction import MAX_USERNAME_LENGTH, request_credentials

        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.console = MagicMock()
        # Accept, then provide very long username
        mock_ctx.get_user_input = MagicMock(side_effect=["yes", "a" * (MAX_USERNAME_LENGTH + 1)])
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="mongodb",
            error_message="Authentication failed"
        )

        self.assertIn("too long", result.lower())

    @patch("merlya.tools.interaction.get_tool_context")
    def test_request_credentials_unknown_service_defaults(self, mock_get_ctx):
        """Test that unknown service type defaults to 'database'."""
        from merlya.tools.interaction import request_credentials

        mock_ctx = MagicMock()
        mock_ctx.credentials = MagicMock()
        mock_ctx.console = MagicMock()
        mock_ctx.get_user_input = MagicMock(return_value="no")
        mock_get_ctx.return_value = mock_ctx

        result = request_credentials(
            target="db-prod-01",
            service="unknown_service",
            error_message="Authentication failed"
        )

        # Should still work (declined), but service should default to database
        self.assertIn("declined", result.lower())


class TestToolSelectorCredentials(unittest.TestCase):
    """Tests for ToolSelector credential error handling."""

    def test_tool_selector_recommends_request_credentials(self):
        """Test that ToolSelector recommends request_credentials for credential errors."""
        from merlya.domains.tools.selector import ToolAction, ToolSelector
        from merlya.triage import ErrorType

        selector = ToolSelector(use_embeddings=False)  # Use heuristics only

        recommendation = selector.select(
            error_type=ErrorType.CREDENTIAL,
            error_message="Authentication failed for mongodb",
            context={"target": "db-prod-01", "command": "mongosh --eval 'rs.status()'"}
        )

        self.assertEqual(recommendation.action, ToolAction.REQUEST_CREDENTIALS)
        self.assertEqual(recommendation.tool_name, "request_credentials")
        self.assertIn("mongodb", recommendation.tool_params.get("service", "").lower())
        self.assertGreaterEqual(recommendation.confidence, 0.8)

    def test_service_detection_from_command(self):
        """Test that service type is correctly detected from command."""
        from merlya.domains.tools.selector import ToolSelector

        selector = ToolSelector(use_embeddings=False)

        # Test MongoDB detection
        service = selector._detect_service_from_context(
            {"command": "mongosh --eval 'db.stats()'"},
            "authentication failed"
        )
        self.assertEqual(service, "mongodb")

        # Test MySQL detection
        service = selector._detect_service_from_context(
            {"command": "mysql -u root -p"},
            "access denied"
        )
        self.assertEqual(service, "mysql")

        # Test PostgreSQL detection
        service = selector._detect_service_from_context(
            {"command": "psql -h localhost"},
            "password authentication failed"
        )
        self.assertEqual(service, "postgresql")


if __name__ == "__main__":
    unittest.main()
