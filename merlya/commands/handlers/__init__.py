"""
Merlya Commands - Command handlers.

Modular handlers organized by domain.
"""

from loguru import logger


def init_commands() -> None:
    """
    Initialize all command handlers.

    Imports trigger registration via decorators.
    """
    # Import all handler modules to register commands
    from merlya.commands.handlers import (
        conversations,
        core,
        hosts,
        mcp,
        model,
        ssh,
        system,
        variables,
    )

    # Prevent unused import warnings
    _ = (core, hosts, ssh, variables, model, conversations, system, mcp)

    logger.debug("✅ Commands initialized")
