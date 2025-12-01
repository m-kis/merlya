from typing import Callable, Dict, Optional


class CommandRegistry:
    """Registry for REPL slash commands."""

    def __init__(self):
        self._commands: Dict[str, str] = {}
        self._handlers: Dict[str, Callable] = {}

    def register(self, command: str, description: str, handler: Callable):
        """Register a new command."""
        self._commands[command] = description
        self._handlers[command] = handler

    def get_handler(self, command: str) -> Optional[Callable]:
        """Get handler for a command."""
        return self._handlers.get(command)

    def get_description(self, command: str) -> Optional[str]:
        """Get description for a command."""
        return self._commands.get(command)

    def list_commands(self) -> Dict[str, str]:
        """List all registered commands."""
        return self._commands.copy()

    def unregister(self, command: str):
        """Unregister a command."""
        if command in self._commands:
            del self._commands[command]
        if command in self._handlers:
            del self._handlers[command]
