import asyncio
from typing import List

from rich.console import Console
from rich.markdown import Markdown

from athena_ai.repl.command_processor.registry import CommandRegistry
from athena_ai.repl.ui import print_message

console = Console()

class CommandExecutor:
    """Executes REPL slash commands."""

    def __init__(self, repl, registry: CommandRegistry):
        self.repl = repl
        self.registry = registry

    def execute(self, command: str) -> bool:
        """
        Execute a slash command.
        Returns True if command was handled, False otherwise.
        """
        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in ['/exit', '/quit']:
            return 'exit'

        # Check for registered handlers first
        handler = self.registry.get_handler(cmd)
        if handler:
            return handler(args)

        # Check for extensible custom commands
        cmd_name = cmd[1:]  # Remove leading /
        custom_cmd = self.repl.command_loader.get(cmd_name)
        if custom_cmd:
            return self._handle_custom_command(custom_cmd, args)

        return False

    def _handle_custom_command(self, custom_cmd, args: List[str]) -> bool:
        """Execute a custom command loaded from markdown."""
        prompt = self.repl.command_loader.expand(custom_cmd, args)
        print_message(f"[cyan]Running /{custom_cmd.name}...[/cyan]\n")

        # Add to conversation and process
        self.repl.conversation_manager.add_user_message(prompt)

        with console.status("[cyan]🦉 Athena is thinking...[/cyan]", spinner="dots"):
            response = asyncio.run(
                self.repl.orchestrator.process_request(user_query=prompt)
            )

        self.repl.conversation_manager.add_assistant_message(response)
        console.print(Markdown(response))
        return True
