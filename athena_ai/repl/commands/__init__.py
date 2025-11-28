"""
REPL command handlers.

This module provides modular command handlers for the Athena REPL.
"""

from athena_ai.repl.commands.context import ContextCommandHandler
from athena_ai.repl.commands.help import SLASH_COMMANDS, HelpCommandHandler
from athena_ai.repl.commands.inventory import InventoryCommandHandler
from athena_ai.repl.commands.model import ModelCommandHandler
from athena_ai.repl.commands.session import SessionCommandHandler
from athena_ai.repl.commands.variables import VariablesCommandHandler

# Re-export CommandHandler and CommandResult from handlers.py for backward compatibility
from athena_ai.repl.handlers import CommandHandler, CommandResult

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
