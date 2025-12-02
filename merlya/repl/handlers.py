"""
Slash command handlers for Merlya REPL.

This module provides the main CommandHandler class that routes
commands to specialized handler modules.
"""
import difflib
import logging
import shlex
from enum import Enum, auto

from rich.markdown import Markdown

from merlya.repl.ui import console, print_error, print_message, print_warning
from merlya.tools.base import get_status_manager

logger = logging.getLogger(__name__)


class CommandResult(Enum):
    """Result type for command handling."""
    EXIT = auto()       # User requested to exit the REPL
    HANDLED = auto()    # Command was recognized and handled successfully
    FAILED = auto()     # Command was recognized but failed during execution
    NOT_HANDLED = auto()  # Command was not recognized


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
        self._cicd_handler = None
        self._stats_handler = None
        self._ssh_handler = None
        self._secret_handler = None
        self._log_handler = None

    @property
    def context_handler(self):
        """Lazy load context handler."""
        if self._context_handler is None:
            from merlya.repl.commands.context import ContextCommandHandler
            self._context_handler = ContextCommandHandler(self.repl)
        return self._context_handler

    @property
    def model_handler(self):
        """Lazy load model handler."""
        if self._model_handler is None:
            from merlya.repl.commands.model import ModelCommandHandler
            self._model_handler = ModelCommandHandler(self.repl)
        return self._model_handler

    @property
    def variables_handler(self):
        """Lazy load variables handler."""
        if self._variables_handler is None:
            from merlya.repl.commands.variables import VariablesCommandHandler
            self._variables_handler = VariablesCommandHandler(self.repl)
        return self._variables_handler

    @property
    def session_handler(self):
        """Lazy load session handler."""
        if self._session_handler is None:
            from merlya.repl.commands.session import SessionCommandHandler
            self._session_handler = SessionCommandHandler(self.repl)
        return self._session_handler

    @property
    def help_handler(self):
        """Lazy load help handler."""
        if self._help_handler is None:
            from merlya.repl.commands.help import HelpCommandHandler
            self._help_handler = HelpCommandHandler(self.repl)
        return self._help_handler

    @property
    def cicd_handler(self):
        """Lazy load CI/CD handler."""
        if self._cicd_handler is None:
            from merlya.repl.commands.cicd import CICDCommandHandler
            self._cicd_handler = CICDCommandHandler(self.repl)
        return self._cicd_handler

    @property
    def stats_handler(self):
        """Lazy load stats handler."""
        if self._stats_handler is None:
            from merlya.repl.commands.stats import StatsCommandHandler
            self._stats_handler = StatsCommandHandler(self.repl)
        return self._stats_handler

    @property
    def ssh_handler(self):
        """Lazy load SSH handler."""
        if self._ssh_handler is None:
            from merlya.repl.commands.ssh import SSHCommandHandler
            self._ssh_handler = SSHCommandHandler(self.repl)
        return self._ssh_handler

    @property
    def secret_handler(self):
        """Lazy load secret handler."""
        if self._secret_handler is None:
            from merlya.repl.commands.secret import SecretCommandHandler
            self._secret_handler = SecretCommandHandler(self.repl)
        return self._secret_handler

    @property
    def log_handler(self):
        """Lazy load log handler."""
        if self._log_handler is None:
            from merlya.repl.commands.log import LogCommandHandler
            self._log_handler = LogCommandHandler(self.repl)
        return self._log_handler

    async def handle_command(self, command: str) -> CommandResult:
        """
        Handle slash commands.

        Returns:
            CommandResult.EXIT if the user requested to exit
            CommandResult.HANDLED if command was recognized and handled
            CommandResult.NOT_HANDLED if command was not recognized
        """
        command = command.strip()
        if not command:
            return CommandResult.NOT_HANDLED

        # Special handling for /variables set commands to preserve raw values
        # This allows setting variables with any content: JSON, hashes, special chars, etc.
        # Example: /variables set CONFIG {"env":"prod","region":"eu-west-1"}
        if command.startswith(('/variables set ', '/variables set-host ')):
            # Split: ['/variables', 'set', 'KEY VALUE_WITH_ANYTHING']
            parts = command.split(maxsplit=2)
            if len(parts) >= 3:
                cmd = parts[0].lower()  # '/variables'
                subcmd = parts[1].lower()  # 'set'
                rest = parts[2]  # 'KEY VALUE_WITH_ANYTHING'

                # Split KEY from VALUE (only on first space)
                key_value_parts = rest.split(maxsplit=1)
                if len(key_value_parts) == 2:
                    key = key_value_parts[0]
                    value = key_value_parts[1]  # Preserve everything as-is
                    # args = [subcmd, key, value] to match expected format
                    args = [subcmd, key, value]
                elif len(key_value_parts) == 1:
                    # Only KEY provided, no VALUE (will trigger error in handler)
                    args = [subcmd, key_value_parts[0]]
                else:
                    args = [subcmd]
            else:
                # Fallback if command format is unexpected
                try:
                    parts = shlex.split(command)
                except ValueError as e:
                    logger.warning(f"Invalid command quoting: {e}")
                    print_error(f"Invalid command syntax: {e}")
                    return CommandResult.FAILED
                cmd = parts[0].lower()
                args = parts[1:]
        else:
            # Use shlex.split() to properly handle quoted arguments for other commands
            # This preserves spaces in quoted strings like: /model set "claude-3-5-sonnet"
            try:
                parts = shlex.split(command)
            except ValueError as e:
                # Handle invalid quoting (unclosed quotes, etc.)
                logger.warning(f"Invalid command quoting: {e}")
                print_error(f"Invalid command syntax: {e}")
                return CommandResult.FAILED

            cmd = parts[0].lower()
            args = parts[1:]

        # Validate that this is a slash command
        if not cmd.startswith('/'):
            return CommandResult.NOT_HANDLED

        if cmd in ['/exit', '/quit']:
            return CommandResult.EXIT

        # Check for extensible custom commands first
        cmd_name = cmd[1:]  # Remove leading /
        custom_cmd = self.repl.command_loader.get(cmd_name)
        if custom_cmd:
            return await self._handle_custom_command(custom_cmd, args)

        # Route to appropriate handler
        handlers = {
            # Help
            '/help': lambda: self.help_handler.show_help(args),

            # Context commands
            '/scan': lambda: self.context_handler.handle_scan(args),
            '/refresh': lambda: self.context_handler.handle_refresh(args),
            '/cache-stats': lambda: self.context_handler.handle_cache_stats(),
            '/permissions': lambda: self.context_handler.handle_permissions(args),
            '/context': lambda: self.context_handler.handle_context(),

            # SSH management (centralized)
            '/ssh': lambda: self.ssh_handler.handle(args),

            # Model commands
            '/model': lambda: self.model_handler.handle(args),

            # Variables commands
            '/variables': lambda: self.variables_handler.handle(args),

            # Secret commands
            '/secret': lambda: self.secret_handler.handle(args),

            # Log commands
            '/log': lambda: self.log_handler.handle(args),

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

            # CI/CD commands
            '/cicd': lambda: self.cicd_handler.handle_cicd(args),
            '/debug-workflow': lambda: self.cicd_handler.handle_debug_workflow(args),

            # Statistics
            '/stats': lambda: self.stats_handler.handle_stats(args),

            # Delegated to core.py (triage, mcp, language)
            '/mcp': lambda: self.repl.handle_mcp_command(args),
            '/language': lambda: self.repl.handle_language_command(args),
            '/triage': lambda: self.repl.handle_triage_command(args),
            '/feedback': lambda: self.repl.handle_feedback_command(args),
            '/triage-stats': lambda: self.repl.handle_triage_stats_command(args),
            '/reload-commands': lambda: self._handle_reload_commands(),
        }

        handler = handlers.get(cmd)
        if handler:
            result = handler()
            # If handler returns a coroutine, await it
            if hasattr(result, '__await__'):
                result = await result
            # Return the handler's CommandResult if it returned one
            if isinstance(result, CommandResult):
                return result
            return CommandResult.HANDLED

        # Collect available commands for suggestion
        available = list(handlers.keys())
        # Add custom commands
        available.extend([f"/{name}" for name in self.repl.command_loader.list_commands()])

        return self._suggest_command(cmd, available)

    def _suggest_command(self, cmd: str, available_commands: list):
        """Suggest closest matching command."""
        matches = difflib.get_close_matches(cmd, available_commands, n=1, cutoff=0.6)
        if matches:
            suggestion = matches[0]
            print_warning(f"Unknown command: {cmd}")
            console.print(f"Did you mean [cyan]{suggestion}[/cyan]?")

            # If suggestion is a known command, show its help
            # We can recursively call handle_command with the suggestion + "help" if appropriate
            # But simpler to just show help for the main command

            # Map suggestion to handler help if possible
            # For now just showing the suggestion is a big improvement
            pass
        else:
            # Check if it looks like a subcommand typo e.g. /model show list -> /model show
            # This is hard without knowing all subcommands.
            # But we can check if the first part matches a known command
            pass

        return CommandResult.NOT_HANDLED

    async def _handle_custom_command(self, custom_cmd, args) -> CommandResult:
        """Execute a custom command loaded from markdown."""
        try:
            prompt = self.repl.command_loader.expand(custom_cmd, args)
            print_message(f"[cyan]Running /{custom_cmd.name}...[/cyan]\n")

            # Add to conversation and process
            self.repl.conversation_manager.add_user_message(prompt)

            # Use StatusManager so tools can pause spinner for user input
            status_manager = get_status_manager()
            status_manager.set_console(console)
            status_manager.start("[cyan]Merlya is thinking...[/cyan]")
            try:
                response = await self.repl.orchestrator.process_request(user_query=prompt)
            finally:
                status_manager.stop()

            # Skip adding/printing if response is None or empty
            if response is None or response == "":
                logger.warning("Received None or empty response from orchestrator")
                return CommandResult.HANDLED

            self.repl.conversation_manager.add_assistant_message(response)
            console.print(Markdown(response))

        except Exception as e:
            logger.exception("Custom command failed")
            print_error(f"Custom command failed: {e}")
            return CommandResult.FAILED

        return CommandResult.HANDLED

    def _handle_inventory(self, args) -> CommandResult:
        """Handle /inventory command for host inventory management."""
        try:
            from merlya.repl.commands.inventory import InventoryCommandHandler
            handler = InventoryCommandHandler()
            handler.handle(args)
            return CommandResult.HANDLED
        except ImportError as e:
            print_error(f"Inventory module not available: {e}")
            return CommandResult.FAILED
        except Exception as e:
            print_error(f"Inventory command failed: {e}")
            return CommandResult.FAILED

    def _handle_reload_commands(self) -> CommandResult:
        """Force reload of custom commands."""
        try:
            self.repl.command_loader.reload()
            count = len(self.repl.command_loader.list_commands())
            print_message(f"[green]✅ Reloaded {count} custom commands[/green]")
            for name in self.repl.command_loader.list_commands():
                print_message(f"  - /{name}")
            return CommandResult.HANDLED
        except Exception as e:
            print_error(f"Failed to reload commands: {e}")
            return CommandResult.FAILED
