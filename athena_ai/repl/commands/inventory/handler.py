"""
Main handler for inventory commands.
Delegates to specific sub-handlers.
"""
from typing import TYPE_CHECKING, List, Optional

from athena_ai.repl.ui import console, print_error
from athena_ai.utils.logger import logger

if TYPE_CHECKING:
    from athena_ai.repl.core import AthenaREPL


class InventoryCommandHandler:
    """Handles /inventory commands."""

    def __init__(self, repl: Optional["AthenaREPL"] = None):
        self.repl = repl
        self._repo = None
        
        # Lazy load sub-handlers
        self._importer = None
        self._viewer = None
        self._manager = None
        self._relations = None

    @property
    def repo(self):
        """Lazy load repository."""
        if self._repo is None:
            try:
                from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
                self._repo = get_inventory_repository()
            except Exception as e:
                raise RuntimeError(f"Failed to initialize inventory repository: {e}") from e
        return self._repo

    @property
    def importer(self):
        """Lazy load importer handler."""
        if self._importer is None:
            try:
                from .importer import InventoryImporter
                # Access repo inside try - its RuntimeError will propagate directly
                self._importer = InventoryImporter(self.repo)
            except ImportError as e:
                raise RuntimeError(f"Failed to import inventory importer: {e}") from e
        return self._importer

    @property
    def viewer(self):
        """Lazy load viewer handler."""
        if self._viewer is None:
            try:
                from .viewer import InventoryViewer
                self._viewer = InventoryViewer(self.repo)
            except ImportError as e:
                raise RuntimeError(f"Failed to import inventory viewer: {e}") from e
        return self._viewer

    @property
    def manager(self):
        """Lazy load manager handler."""
        if self._manager is None:
            try:
                from .manager import InventoryManager
                self._manager = InventoryManager(self.repo)
            except ImportError as e:
                raise RuntimeError(f"Failed to import inventory manager: {e}") from e
        return self._manager

    @property
    def relations(self):
        """Lazy load relations handler."""
        if self._relations is None:
            try:
                from .relations import RelationsHandler
                self._relations = RelationsHandler(self.repo)
            except ImportError as e:
                raise RuntimeError(f"Failed to import relations handler: {e}") from e
        return self._relations

    def handle(self, args: List[str]) -> bool:
        """
        Handle /inventory command.

        Returns True to indicate the REPL should continue (always returns True).
        """
        if not args:
            self._show_help()
            return True

        cmd = args[0].lower()
        cmd_args = args[1:]

        handlers = {
            "add": lambda a: self.importer.handle_add(a),
            "import": lambda a: self.importer.handle_add(a),  # Alias
            "add-host": lambda a: self.manager.handle_add_host(a, self.repl),
            "list": lambda a: self.viewer.handle_list(a),
            "ls": lambda a: self.viewer.handle_list(a),  # Alias
            "show": lambda a: self.viewer.handle_show(a),
            "search": lambda a: self.viewer.handle_search(a),
            "find": lambda a: self.viewer.handle_search(a),  # Alias
            "remove": lambda a: self.manager.handle_remove(a),
            "delete": lambda a: self.manager.handle_remove(a),  # Alias
            "rm": lambda a: self.manager.handle_remove(a),  # Alias
            "export": lambda a: self.manager.handle_export(a),
            "snapshot": lambda a: self.manager.handle_snapshot(a),
            "relations": lambda a: self.relations.handle_relations(a),
            "stats": lambda a: self.viewer.handle_stats(a),
            "ssh-key": lambda a: self.manager.handle_ssh_key(a, self.repl),
            "help": lambda _: self._show_help(),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                handler(cmd_args)
            except (KeyboardInterrupt, SystemExit):
                # Re-raise critical exceptions - don't suppress user interrupts or exits
                raise
            except Exception as e:
                # Log full traceback for debugging, show concise message to user
                logger.exception(f"Error executing inventory command '{cmd}': {e}")
                print_error(f"Command failed: {e}")
            return True

        print_error(f"Unknown inventory command: {cmd}")
        self._show_help()
        return True

    def _show_help(self) -> bool:
        """Show inventory command help."""
        console.print("\n[bold cyan]Inventory Commands[/bold cyan]\n")
        console.print("  /inventory add <file>         Import hosts from file (CSV, JSON, YAML, etc.)")
        console.print("  /inventory add /etc/hosts     Import from system file")
        console.print("  /inventory add-host <name>    Add a single host interactively")
        console.print("  /inventory list               List all inventory sources")
        console.print("  /inventory show [source]      Show hosts (optionally from specific source)")
        console.print("  /inventory search <pattern>   Search hosts by name/IP")
        console.print("  /inventory remove <source>    Remove an inventory source")
        console.print("  /inventory export <file>      Export inventory to file")
        console.print("  /inventory snapshot [name]    Create inventory snapshot")
        console.print("  /inventory relations          Manage host relations")
        console.print("  /inventory stats              Show inventory statistics")
        console.print()
        console.print("[bold]SSH Key Management:[/bold]")
        console.print("  /inventory ssh-key <host> set <key_path>   Set SSH key for host")
        console.print("  /inventory ssh-key <host> passphrase       Set passphrase (stored as secret)")
        console.print("  /inventory ssh-key <host> show             Show SSH key config")
        console.print("  /inventory ssh-key <host> clear            Remove SSH key config")
        console.print()
        console.print("[bold]Options:[/bold]")
        console.print("  --limit N                     Limit results (default: show 100, search 50)")
        console.print()
        console.print("[bold]Supported Formats:[/bold]")
        console.print("  CSV, JSON, YAML, TXT, INI (Ansible), /etc/hosts, ~/.ssh/config")
        console.print("  Non-standard formats are parsed using AI")
        console.print()
        console.print("[bold]Host References (@hostname):[/bold]")
        console.print("  Reference hosts in prompts: [cyan]check nginx on @web-prod-01[/cyan]")
        console.print("  Auto-completes from inventory (press Tab)")
        return True
