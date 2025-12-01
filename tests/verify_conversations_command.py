"""
Tests for SessionCommandHandler - /conversations and related commands.

This test file verifies the conversation management functionality in the REPL.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path FIRST
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now we can import
from athena_ai.repl.commands.session import SessionCommandHandler


class TestConversationsCommand(unittest.TestCase):
    def setUp(self):
        self.mock_repl = MagicMock()
        self.mock_manager = MagicMock()
        self.mock_repl.conversation_manager = self.mock_manager

        # Mock current conversation
        self.mock_current_conv = MagicMock()
        self.mock_current_conv.id = "conv_current"
        self.mock_manager.current_conversation = self.mock_current_conv

        self.handler = SessionCommandHandler(self.mock_repl)

        # Mock console to prevent actual output
        self.console_patcher = patch('athena_ai.repl.commands.session.console')
        self.mock_console = self.console_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()

    def test_list_default(self):
        """Test /conversations (no args) defaults to list."""
        self.mock_manager.list_conversations.return_value = [
            {'id': 'conv_1', 'title': 'Test 1', 'message_count': 5, 'token_count': 100, 'updated_at': '2023-01-01'},
            {'id': 'conv_current', 'title': 'Current', 'message_count': 10, 'token_count': 200, 'updated_at': '2023-01-02'}
        ]

        self.handler.handle_conversations([])

        self.mock_manager.list_conversations.assert_called_with(limit=20)
        self.mock_console.print.assert_called()

    def test_list_explicit(self):
        """Test /conversations list."""
        self.mock_manager.list_conversations.return_value = []
        self.handler.handle_conversations(['list'])
        self.mock_manager.list_conversations.assert_called_with(limit=20)

    def test_check_found_in_list(self):
        """Test /conversations check <id> found in recent list."""
        target_id = 'conv_target'
        self.mock_manager.list_conversations.return_value = [
            {'id': target_id, 'title': 'Target', 'message_count': 5, 'token_count': 100}
        ]

        # Mock store load for preview with real string values
        mock_conv = MagicMock()
        mock_conv.id = target_id
        mock_conv.title = "Target"
        mock_conv.message_count = 5
        mock_conv.token_count = 100
        mock_conv.created_at = "2023-01-01"
        mock_conv.updated_at = "2023-01-02"

        mock_msg1 = MagicMock()
        mock_msg1.role = 'user'
        mock_msg1.content = 'Hello'
        mock_msg2 = MagicMock()
        mock_msg2.role = 'assistant'
        mock_msg2.content = 'Hi there'
        mock_conv.messages = [mock_msg1, mock_msg2]

        self.mock_manager.history.store.load_conversation.return_value = mock_conv

        self.handler.handle_conversations(['check', target_id])

        self.mock_console.print.assert_called()

    def test_check_load_from_store(self):
        """Test /conversations check <id> loading from store."""
        target_id = 'conv_old'
        self.mock_manager.list_conversations.return_value = []

        mock_conv = MagicMock()
        mock_conv.id = target_id
        mock_conv.title = "Old Conv"
        mock_conv.message_count = 10
        mock_conv.token_count = 500
        mock_conv.messages = []

        self.mock_manager.history.store.load_conversation.return_value = mock_conv

        self.handler.handle_conversations(['check', target_id])

        self.mock_console.print.assert_called()

    def test_set(self):
        """Test /conversations set <id> calls load."""
        with patch.object(self.handler, 'handle_load') as mock_load:
            self.handler.handle_conversations(['set', 'conv_123'])
            mock_load.assert_called_with(['conv_123'])

    def test_help(self):
        """Test /conversations help."""
        self.handler.handle_conversations(['help'])
        self.mock_console.print.assert_called()


class TestConversationIdValidation(unittest.TestCase):
    """Test conversation ID validation for security."""

    def setUp(self):
        self.mock_repl = MagicMock()
        self.mock_manager = MagicMock()
        self.mock_repl.conversation_manager = self.mock_manager
        self.mock_manager.current_conversation = None
        self.handler = SessionCommandHandler(self.mock_repl)

        # Mock console and print functions
        self.console_patcher = patch('athena_ai.repl.commands.session.console')
        self.error_patcher = patch('athena_ai.repl.commands.session.print_error')
        self.mock_console = self.console_patcher.start()
        self.mock_print_error = self.error_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.error_patcher.stop()

    def test_valid_conversation_id(self):
        """Test that valid conversation IDs pass validation."""
        valid_ids = [
            'conv_123',
            'my-conversation',
            'abc123',
            'UPPERCASE_ID',
            'mixed-Case_123',
        ]
        for conv_id in valid_ids:
            is_valid, error = self.handler._validate_conversation_id(conv_id)
            self.assertTrue(is_valid, f"Expected {conv_id} to be valid")
            self.assertIsNone(error)

    def test_path_traversal_rejected(self):
        """Test that path traversal attempts are rejected."""
        malicious_ids = [
            '../../../etc/passwd',
            '..\\..\\windows\\system32',
            'conv/../secret',
            'normal/path',
            'back\\slash',
        ]
        for conv_id in malicious_ids:
            is_valid, error = self.handler._validate_conversation_id(conv_id)
            self.assertFalse(is_valid, f"Expected {conv_id} to be rejected")
            self.assertIsNotNone(error)

    def test_empty_id_rejected(self):
        """Test that empty IDs are rejected."""
        is_valid, error = self.handler._validate_conversation_id('')
        self.assertFalse(is_valid)
        self.assertIn('empty', error.lower())

    def test_too_long_id_rejected(self):
        """Test that excessively long IDs are rejected."""
        long_id = 'a' * 300
        is_valid, error = self.handler._validate_conversation_id(long_id)
        self.assertFalse(is_valid)
        self.assertIn('too long', error.lower())

    def test_special_chars_rejected(self):
        """Test that special characters are rejected."""
        invalid_ids = [
            'conv@123',
            'my!conversation',
            'space here',
            'tab\there',
            'newline\nhere',
        ]
        for conv_id in invalid_ids:
            is_valid, error = self.handler._validate_conversation_id(conv_id)
            self.assertFalse(is_valid, f"Expected {conv_id!r} to be rejected")

    def test_check_with_invalid_id(self):
        """Test /conversations check rejects invalid IDs."""
        result = self.handler.handle_conversations(['check', '../../../etc/passwd'])
        self.assertTrue(result)  # Command handled
        self.mock_print_error.assert_called()
        # Verify load_conversation was NOT called
        self.mock_manager.history.store.load_conversation.assert_not_called()

    def test_load_with_invalid_id(self):
        """Test /load rejects invalid IDs."""
        result = self.handler.handle_load(['conv@invalid'])
        self.assertTrue(result)
        self.mock_print_error.assert_called()
        self.mock_manager.load_conversation.assert_not_called()

    def test_delete_with_invalid_id(self):
        """Test /delete rejects invalid IDs."""
        result = self.handler.handle_delete(['../../secret'])
        self.assertTrue(result)
        self.mock_print_error.assert_called()
        self.mock_manager.delete_conversation.assert_not_called()


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        self.mock_repl = MagicMock()
        self.mock_manager = MagicMock()
        self.mock_repl.conversation_manager = self.mock_manager
        self.mock_manager.current_conversation = None
        self.handler = SessionCommandHandler(self.mock_repl)

        self.console_patcher = patch('athena_ai.repl.commands.session.console')
        self.error_patcher = patch('athena_ai.repl.commands.session.print_error')
        self.warning_patcher = patch('athena_ai.repl.commands.session.print_warning')
        self.mock_console = self.console_patcher.start()
        self.mock_print_error = self.error_patcher.start()
        self.mock_print_warning = self.warning_patcher.start()

    def tearDown(self):
        self.console_patcher.stop()
        self.error_patcher.stop()
        self.warning_patcher.stop()

    def test_list_empty_conversations(self):
        """Test /conversations list when no conversations exist."""
        self.mock_manager.list_conversations.return_value = []
        result = self.handler.handle_conversations(['list'])
        self.assertTrue(result)
        self.mock_print_warning.assert_called()

    def test_list_exception_handling(self):
        """Test /conversations list handles exceptions gracefully."""
        self.mock_manager.list_conversations.side_effect = Exception("DB error")
        result = self.handler.handle_conversations(['list'])
        self.assertTrue(result)
        self.mock_print_error.assert_called()

    def test_check_nonexistent_id(self):
        """Test /conversations check with ID that doesn't exist."""
        self.mock_manager.list_conversations.return_value = []
        self.mock_manager.history.store.load_conversation.return_value = None

        result = self.handler.handle_conversations(['check', 'nonexistent'])
        self.assertTrue(result)
        self.mock_print_warning.assert_called()

    def test_load_exception_handling(self):
        """Test /load handles exceptions gracefully."""
        self.mock_manager.load_conversation.side_effect = Exception("DB error")
        result = self.handler.handle_load(['valid_id'])
        self.assertTrue(result)
        self.mock_print_error.assert_called()

    def test_delete_keyboard_interrupt(self):
        """Test /delete handles Ctrl+C during confirmation."""
        with patch('builtins.input', side_effect=KeyboardInterrupt):
            result = self.handler.handle_delete(['conv_123'])
        self.assertTrue(result)
        self.mock_manager.delete_conversation.assert_not_called()
        self.mock_print_warning.assert_called()

    def test_delete_user_cancels(self):
        """Test /delete when user types 'n'."""
        with patch('builtins.input', return_value='n'):
            result = self.handler.handle_delete(['conv_123'])
        self.assertTrue(result)
        self.mock_manager.delete_conversation.assert_not_called()

    def test_unknown_subcommand(self):
        """Test unknown subcommand shows help."""
        result = self.handler.handle_conversations(['invalid_subcommand'])
        self.assertTrue(result)
        self.mock_print_error.assert_called()
        self.mock_console.print.assert_called()  # Help table printed

    def test_unexpected_exception_in_conversations(self):
        """Test unexpected exception is caught and logged."""
        # Force an exception in subcommand routing
        with patch.object(
            self.handler, '_handle_conversations_list', side_effect=RuntimeError("Boom")
        ):
            result = self.handler.handle_conversations([])
        self.assertTrue(result)
        self.mock_print_error.assert_called()


if __name__ == '__main__':
    unittest.main()
