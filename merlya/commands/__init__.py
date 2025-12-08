"""
Merlya Commands - Slash command handlers.

Implements /help, /hosts, /ssh, /variable, /secret, etc.
"""

from merlya.commands.handlers import init_commands
from merlya.commands.registry import (
    Command,
    CommandRegistry,
    CommandResult,
    command,
    get_registry,
    subcommand,
)

__all__ = [
    "Command",
    "CommandRegistry",
    "CommandResult",
    "command",
    "get_registry",
    "init_commands",
    "subcommand",
]
