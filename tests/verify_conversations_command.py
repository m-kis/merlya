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

if __name__ == '__main__':
    unittest.main()
