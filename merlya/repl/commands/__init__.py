"""
REPL command handlers.

This module provides modular command handlers for the Merlya REPL.
"""

from merlya.repl.commands.context import ContextCommandHandler
from merlya.repl.commands.help import SLASH_COMMANDS, HelpCommandHandler
from merlya.repl.commands.inventory import InventoryCommandHandler
from merlya.repl.commands.model import ModelCommandHandler
from merlya.repl.commands.session import SessionCommandHandler
from merlya.repl.commands.variables import VariablesCommandHandler

# Re-export CommandHandler and CommandResult from handlers.py for backward compatibility
from merlya.repl.handlers import CommandHandler, CommandResult

__all__ = [
    "SLASH_COMMANDS",
    "CommandHandler",
    "CommandResult",
    "HelpCommandHandler",
    "ContextCommandHandler",
    "ModelCommandHandler",
    "VariablesCommandHandler",
    "SessionCommandHandler",
    "InventoryCommandHandler",
]
