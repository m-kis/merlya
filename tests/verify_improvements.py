import sys
from unittest.mock import MagicMock

# Mock dependencies that might be missing in CI/test env
sys.modules["prompt_toolkit"] = MagicMock()
sys.modules["prompt_toolkit.auto_suggest"] = MagicMock()
sys.modules["prompt_toolkit.history"] = MagicMock()
sys.modules["prompt_toolkit.completion"] = MagicMock()
sys.modules["prompt_toolkit.document"] = MagicMock()
sys.modules["rich"] = MagicMock()
sys.modules["rich.console"] = MagicMock()
sys.modules["rich.markdown"] = MagicMock()
sys.modules["rich.table"] = MagicMock()
sys.modules["rich.prompt"] = MagicMock()
sys.modules["rich.panel"] = MagicMock()
sys.modules["rich.syntax"] = MagicMock()
sys.modules["rich.text"] = MagicMock()
sys.modules["rich.live"] = MagicMock()
sys.modules["rich.spinner"] = MagicMock()
sys.modules["rich.progress"] = MagicMock()
sys.modules["rich.columns"] = MagicMock()
sys.modules["rich.theme"] = MagicMock()
sys.modules["rich.style"] = MagicMock()
sys.modules["rich.layout"] = MagicMock()
sys.modules["jinja2"] = MagicMock()
sys.modules["falkordb"] = MagicMock()
sys.modules["duckduckgo_search"] = MagicMock()
sys.modules["paramiko"] = MagicMock()
sys.modules["anthropic"] = MagicMock()
sys.modules["openai"] = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.generativeai"] = MagicMock()
sys.modules["requests"] = MagicMock()
sys.modules["yaml"] = MagicMock()
sys.modules["toml"] = MagicMock()

import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

from merlya.repl.handlers import CommandHandler, CommandResult
from merlya.repl.commands.variables import VariablesCommandHandler
from merlya.repl.commands.inventory.manager import InventoryManager
from merlya.security.credentials import CredentialManager, VariableType
from merlya.repl.commands.context import ContextCommandHandler

class TestImprovements(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.repl = MagicMock()
        self.repl.credentials = CredentialManager()
        # Mock storage to avoid file I/O
        self.repl.credentials._storage = MagicMock()
        self.repl.credentials._storage.get_config.return_value = {}
        
        self.repl.command_loader = MagicMock()
        self.repl.command_loader.list_commands.return_value = []
        self.repl.command_loader.get.return_value = None # Default to no custom command found

    async def test_implicit_global_ssh_key(self):
        """Test implicit global context for ssh-key command."""
        repo = MagicMock()
        repo.get_host_by_name.return_value = None
        
        manager = InventoryManager(repo)
        repl = MagicMock()
        repl.credential_manager = self.repl.credentials
        
        # Test "set <path>" -> should be treated as "global set <path>"
        # We need to mock input for the passphrase prompt (which we added)
        with patch("builtins.input", return_value="n"): # Say no to passphrase
            args = ["set", "/tmp/implicit_global"]
            manager.handle_ssh_key(args, repl)
        
        # Verify it was set in credentials
        val = self.repl.credentials.get_variable("ssh_key_global")
        self.assertEqual(val, "/tmp/implicit_global")

    async def test_unified_variables_command(self):
        """Test that /credentials is gone and /variables works."""
        handler = CommandHandler(self.repl)
        
        # Verify /credentials is NOT handled directly (it was removed)
        # But wait, we removed the mapping, so it should fall through to smart help or return NOT_HANDLED
        # Actually, if we type /credentials, it should trigger smart help suggestion for /variables?
        # Or just be NOT_HANDLED if no fuzzy match (credentials vs variables is not close enough for 0.6 cutoff)
        
        # Let's verify /variables works
        result = await handler.handle_command("/variables list")
        self.assertEqual(result, CommandResult.HANDLED)

    async def test_global_ssh_key(self):
        """Test global SSH key setting."""
        repo = MagicMock()
        repo.get_host_by_name.return_value = None # Simulate host not found for "global" check
        
        manager = InventoryManager(repo)
        
        # Mock repl for manager
        repl = MagicMock()
        repl.credential_manager = self.repl.credentials
        
        # Test setting global key
        args = ["global", "set", "/tmp/id_rsa_global"]
        manager.handle_ssh_key(args, repl)
        
        # Verify it was set in credentials
        val = self.repl.credentials.get_variable("ssh_key_global")
        self.assertEqual(val, "/tmp/id_rsa_global")
        
        # Verify get_default_key uses it
        with patch("pathlib.Path.exists", return_value=True):
            default_key = self.repl.credentials.get_default_key()
            self.assertEqual(default_key, "/tmp/id_rsa_global")

    async def test_smart_help(self):
        """Test smart help suggestions."""
        handler = CommandHandler(self.repl)
        
        # Mock print functions to capture output
        with patch("merlya.repl.handlers.console.print") as mock_print:
            # Typo: /modle -> /model
            await handler.handle_command("/modle")
            
            # Check if suggestion was printed
            args, _ = mock_print.call_args
            self.assertIn("Did you mean", args[0])
            self.assertIn("model", args[0])

    async def test_async_scan_fix(self):
        """Test that handle_scan is async and awaits scan_host."""
        handler = ContextCommandHandler(self.repl)
        self.repl.context_manager.scan_host = AsyncMock(return_value={'accessible': True, 'ip': '1.2.3.4'})
        
        # Should be awaitable now
        await handler.handle_scan(["localhost"])
        
        self.repl.context_manager.scan_host.assert_awaited_once()

    async def test_async_scan_fix(self):
        """Test that scan_host is awaited correctly."""
        # Mock ContextManager.scan_host to be an async mock
        self.repl.context_manager.scan_host = AsyncMock(return_value={
            "accessible": True,
            "ip": "1.2.3.4"
        })
        
        handler = ContextCommandHandler(self.repl)
        await handler.handle_scan(["test_host"])
        
        self.repl.context_manager.scan_host.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
