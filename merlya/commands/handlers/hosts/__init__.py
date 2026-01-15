"""
Merlya Commands - Host management handlers.

Implements /hosts command with subcommands: list, add, show, delete,
tag, untag, edit, check, import, export.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# IMPORTANT: The parent command MUST be defined and registered BEFORE
# importing subcommands, because @subcommand decorator registers at import time.


@command("hosts", "Manage hosts inventory", "/hosts <subcommand>")
async def cmd_hosts(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage hosts inventory."""
    # Import here to avoid circular import at module level
    from .list import cmd_hosts_list

    if not args:
        return await cmd_hosts_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help hosts` for available commands.",
        show_help=True,
    )


# Now import subcommands AFTER the parent command is registered
# Import the import_hosts function for backward compatibility with tests
from merlya.commands.handlers.hosts_io import import_hosts  # noqa: E402

from .add import cmd_hosts_add  # noqa: E402
from .check import (  # noqa: E402
    HostCheckResult,
    SSHConnectionTestResult,
    cmd_hosts_check,
    test_ssh_connection,
)
from .delete import cmd_hosts_delete, cmd_hosts_flush  # noqa: E402
from .edit import cmd_hosts_edit, cmd_hosts_show  # noqa: E402
from .io import cmd_hosts_export, cmd_hosts_import  # noqa: E402
from .list import cmd_hosts_list  # noqa: E402
from .tags import cmd_hosts_tag, cmd_hosts_untag  # noqa: E402

# Backward compatibility aliases
_SSHConnectionTestResult = SSHConnectionTestResult
_HostCheckResult = HostCheckResult
_test_ssh_connection = test_ssh_connection


__all__ = [
    # Types (backward compatibility)
    "HostCheckResult",
    "SSHConnectionTestResult",
    "_HostCheckResult",
    "_SSHConnectionTestResult",
    "_test_ssh_connection",
    # Main command
    "cmd_hosts",
    # Subcommands
    "cmd_hosts_add",
    "cmd_hosts_check",
    "cmd_hosts_delete",
    "cmd_hosts_edit",
    "cmd_hosts_export",
    "cmd_hosts_flush",
    "cmd_hosts_import",
    "cmd_hosts_list",
    "cmd_hosts_show",
    "cmd_hosts_tag",
    "cmd_hosts_untag",
    "import_hosts",
    "test_ssh_connection",
]
