"""
Merlya Commands - Command registry.

Manages slash command registration and dispatch.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Command handler type
CommandHandler = Callable[
    ["SharedContext", list[str]],
    Coroutine[Any, Any, "CommandResult"],
]


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    message: str
    data: Any = None
    show_help: bool = False


@dataclass
class Command:
    """Command definition."""

    name: str
    description: str
    usage: str
    handler: CommandHandler
    aliases: list[str] = field(default_factory=list)
    subcommands: dict[str, Command] = field(default_factory=dict)
    description_key: str | None = None
    usage_key: str | None = None


class CommandRegistry:
    """
    Registry for slash commands.

    Handles command registration, parsing, and dispatch.
    """

    def __init__(self) -> None:
        """Initialize registry."""
        self._commands: dict[str, Command] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        name: str,
        description: str,
        usage: str,
        handler: CommandHandler,
        aliases: list[str] | None = None,
    ) -> Command:
        """
        Register a command.

        Args:
            name: Command name (without /).
            description: Short description.
            usage: Usage string.
            handler: Async handler function.
            aliases: Optional command aliases.

        Returns:
            Registered Command.
        """
        cmd = Command(
            name=name,
            description=description,
            usage=usage,
            handler=handler,
            aliases=aliases or [],
            description_key=f"commands_meta.{name}.description",
            usage_key=f"commands_meta.{name}.usage",
        )
        self._commands[name] = cmd

        # Register aliases
        for alias in cmd.aliases:
            self._aliases[alias] = name

        logger.debug(f"📋 Registered command: /{name}")
        return cmd

    def register_subcommand(
        self,
        parent: str,
        name: str,
        description: str,
        usage: str,
        handler: CommandHandler,
    ) -> None:
        """
        Register a subcommand.

        Args:
            parent: Parent command name.
            name: Subcommand name.
            description: Short description.
            usage: Usage string.
            handler: Async handler function.
        """
        if parent not in self._commands:
            raise ValueError(f"Parent command '{parent}' not registered")

        subcmd = Command(
            name=name,
            description=description,
            usage=usage,
            handler=handler,
            description_key=f"commands_meta.{parent}.{name}.description",
            usage_key=f"commands_meta.{parent}.{name}.usage",
        )
        self._commands[parent].subcommands[name] = subcmd
        logger.debug(f"📋 Registered subcommand: /{parent} {name}")

    def get(self, name: str) -> Command | None:
        """Get a command by name or alias."""
        if name in self._commands:
            return self._commands[name]
        if name in self._aliases:
            return self._commands[self._aliases[name]]
        return None

    def all(self) -> list[Command]:
        """Get all registered commands."""
        return list(self._commands.values())

    def parse(self, input_text: str) -> tuple[str, list[str]] | None:
        """
        Parse a slash command.

        Args:
            input_text: User input.

        Returns:
            Tuple of (command_name, args) or None if not a command.
        """
        if not input_text.startswith("/"):
            return None

        # Split command and args
        parts = input_text[1:].split()
        if not parts:
            return None

        return parts[0].lower(), parts[1:]

    async def execute(
        self,
        ctx: SharedContext,
        input_text: str,
    ) -> CommandResult | None:
        """
        Execute a slash command.

        Args:
            ctx: Shared context.
            input_text: User input.

        Returns:
            CommandResult or None if not a command.
        """
        parsed = self.parse(input_text)
        if not parsed:
            return None

        cmd_name, args = parsed

        # Get command
        cmd = self.get(cmd_name)
        if not cmd:
            return CommandResult(
                success=False,
                message=f"Unknown command: /{cmd_name}",
            )

        # Check for subcommand
        if args and args[0] in cmd.subcommands:
            subcmd = cmd.subcommands[args[0]]
            return await subcmd.handler(ctx, args[1:])

        # Execute main command
        try:
            return await cmd.handler(ctx, args)
        except Exception as e:
            logger.error(f"❌ Command error: {e}")
            return CommandResult(
                success=False,
                message=f"Error executing /{cmd_name}: {e}",
            )

    def get_completions(self, partial: str) -> list[str]:
        """
        Get command completions for autocompletion.

        Args:
            partial: Partial command input.

        Returns:
            List of matching commands.
        """
        if not partial.startswith("/"):
            return []

        prefix = partial[1:].lower()
        completions = []

        for name in self._commands:
            if name.startswith(prefix):
                completions.append(f"/{name}")

        for alias in self._aliases:
            if alias.startswith(prefix):
                completions.append(f"/{alias}")

        return sorted(completions)


# Global registry instance
_registry: CommandRegistry | None = None


def get_registry() -> CommandRegistry:
    """Get the global command registry."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (for tests)."""
    global _registry
    _registry = None


def command(
    name: str,
    description: str,
    usage: str = "",
    aliases: list[str] | None = None,
) -> Callable[[CommandHandler], CommandHandler]:
    """
    Decorator to register a command.

    Usage:
        @command("help", "Show help", "/help [command]")
        async def cmd_help(ctx, args):
            ...
    """

    def decorator(handler: CommandHandler) -> CommandHandler:
        get_registry().register(name, description, usage, handler, aliases)
        return handler

    return decorator


def subcommand(
    parent: str,
    name: str,
    description: str,
    usage: str = "",
) -> Callable[[CommandHandler], CommandHandler]:
    """
    Decorator to register a subcommand.

    Usage:
        @subcommand("hosts", "list", "List all hosts")
        async def cmd_hosts_list(ctx, args):
            ...
    """

    def decorator(handler: CommandHandler) -> CommandHandler:
        get_registry().register_subcommand(parent, name, description, usage, handler)
        return handler

    return decorator
