"""
Slash command handlers for Athena REPL.

This module provides the main CommandHandler class that routes
commands to specialized handler modules.
"""
import asyncio
from typing import Union

from rich.markdown import Markdown

from athena_ai.repl.ui import console, print_error, print_message
from athena_ai.tools.base import get_status_manager

# Re-export SLASH_COMMANDS for backward compatibility
from athena_ai.repl.commands.help import SLASH_COMMANDS


def _run_async(coro):
    """
    Run async coroutine safely, handling both sync and async contexts.

    If already in an event loop, uses a thread pool.
    Otherwise, uses asyncio.run().
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)

    # Already in an event loop - need alternative approach
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


class CommandHandler:
    """
    Handles slash commands for the REPL.

    Routes commands to specialized handler modules for better organization.
    """

    def __init__(self, repl):
        """
        Initialize with reference to the main REPL instance.
        This allows access to orchestrator, managers, etc.
        """
        self.repl = repl

        # Lazy-loaded handlers
        self._context_handler = None
        self._model_handler = None
        self._variables_handler = None
        self._session_handler = None
        self._help_handler = None

    @property
    def context_handler(self):
        """Lazy load context handler."""
        if self._context_handler is None:
            from athena_ai.repl.commands.context import ContextCommandHandler
            self._context_handler = ContextCommandHandler(self.repl)
        return self._context_handler

    @property
    def model_handler(self):
        """Lazy load model handler."""
        if self._model_handler is None:
            from athena_ai.repl.commands.model import ModelCommandHandler
            self._model_handler = ModelCommandHandler(self.repl)
        return self._model_handler

    @property
    def variables_handler(self):
        """Lazy load variables handler."""
        if self._variables_handler is None:
            from athena_ai.repl.commands.variables import VariablesCommandHandler
            self._variables_handler = VariablesCommandHandler(self.repl)
        return self._variables_handler

    @property
    def session_handler(self):
        """Lazy load session handler."""
        if self._session_handler is None:
            from athena_ai.repl.commands.session import SessionCommandHandler
            self._session_handler = SessionCommandHandler(self.repl)
        return self._session_handler

    @property
    def help_handler(self):
        """Lazy load help handler."""
        if self._help_handler is None:
            from athena_ai.repl.commands.help import HelpCommandHandler
            self._help_handler = HelpCommandHandler(self.repl)
        return self._help_handler

    def handle_command(self, command: str) -> Union[bool, str]:
        """
        Handle slash commands.

        Returns:
            True if command was handled
            False if command was not recognized
            'exit' if the user requested to exit
        """
        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in ['/exit', '/quit']:
            return 'exit'

        # Check for extensible custom commands first
        cmd_name = cmd[1:]  # Remove leading /
        custom_cmd = self.repl.command_loader.get(cmd_name)
        if custom_cmd:
            return self._handle_custom_command(custom_cmd, args)

        # Route to appropriate handler
        handlers = {
            # Help
            '/help': lambda: self.help_handler.show_help(),

            # Context commands
            '/scan': lambda: self.context_handler.handle_scan(args),
            '/refresh': lambda: self.context_handler.handle_refresh(args),
            '/cache-stats': lambda: self.context_handler.handle_cache_stats(),
            '/ssh-info': lambda: self.context_handler.handle_ssh_info(),
            '/permissions': lambda: self.context_handler.handle_permissions(args),
            '/context': lambda: self.context_handler.handle_context(),

            # Model commands
            '/model': lambda: self.model_handler.handle(args),

            # Variables commands
            '/variables': lambda: self.variables_handler.handle(args),
            '/credentials': lambda: self.variables_handler.handle(args),

            # Session/conversation commands
            '/session': lambda: self.session_handler.handle_session(args),
            '/conversations': lambda: self.session_handler.handle_conversations(args),
            '/new': lambda: self.session_handler.handle_new(args),
            '/load': lambda: self.session_handler.handle_load(args),
            '/compact': lambda: self.session_handler.handle_compact(args),
            '/delete': lambda: self.session_handler.handle_delete(args),
            '/reset': lambda: self.session_handler.handle_reset(),

            # Inventory (already modularized)
            '/inventory': lambda: self._handle_inventory(args),

            # Delegated to core.py (triage, mcp, language)
            '/mcp': lambda: self.repl._handle_mcp_command(args),
            '/language': lambda: self.repl._handle_language_command(args),
            '/triage': lambda: self.repl._handle_triage_command(args),
            '/feedback': lambda: self.repl._handle_feedback_command(args),
            '/triage-stats': lambda: self.repl._handle_triage_stats_command(args),
        }

        handler = handlers.get(cmd)
        if handler:
            return handler()

        return False

    def _handle_custom_command(self, custom_cmd, args):
        """Execute a custom command loaded from markdown."""
        try:
            prompt = self.repl.command_loader.expand(custom_cmd, args)
            print_message(f"[cyan]Running /{custom_cmd.name}...[/cyan]\n")

            # Add to conversation and process
            self.repl.conversation_manager.add_user_message(prompt)

            # Use StatusManager so tools can pause spinner for user input
            status_manager = get_status_manager()
            status_manager.set_console(console)
            status_manager.start("[cyan]Athena is thinking...[/cyan]")
            try:
                response = _run_async(
                    self.repl.orchestrator.process_request(user_query=prompt)
                )
            finally:
                status_manager.stop()

            # Handle None or empty response
            if not response:
                response = "*No response from assistant*"

            self.repl.conversation_manager.add_assistant_message(response)
            console.print(Markdown(response))

        except Exception as e:
            print_error(f"Custom command failed: {e}")

        return True

    def _handle_inventory(self, args):
        """Handle /inventory command for host inventory management."""
        try:
            from athena_ai.repl.commands.inventory import InventoryCommandHandler
            handler = InventoryCommandHandler()
            return handler.handle(args)
        except ImportError as e:
            print_error(f"Inventory module not available: {e}")
            return True
        except Exception as e:
            print_error(f"Inventory command failed: {e}")
            return True
