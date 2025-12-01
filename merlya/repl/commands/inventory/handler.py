"""
Main handler for inventory commands.
Delegates to specific sub-handlers.
"""
from typing import TYPE_CHECKING, List, Optional

from merlya.repl.ui import console, print_error
from merlya.utils.logger import logger

if TYPE_CHECKING:
    from merlya.repl.core import MerlyaREPL


class InventoryCommandHandler:
    """Handles /inventory commands."""

    def __init__(self, repl: Optional["MerlyaREPL"] = None):
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
                from merlya.memory.persistence.inventory_repository import get_inventory_repository
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
            "quick-add": lambda a: self._handle_quick_add(a),  # Simplified add
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
            "setup": lambda a: self._handle_setup_wizard(),  # Interactive setup
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

    def _handle_quick_add(self, args: List[str]) -> bool:
        """
        Quick add host(s) with minimal interaction.

        Usage:
            /inventory quick-add hostname [ip] [--env env]
            /inventory quick-add host1,host2,host3

        Examples:
            /inventory quick-add web-server-01
            /inventory quick-add db-prod-01 10.0.0.50 --env production
            /inventory quick-add web-01,web-02,web-03
        """
        from merlya.repl.ui import print_success, print_warning

        if not args:
            console.print("[yellow]Usage:[/yellow] /inventory quick-add <hostname> [ip] [--env environment]")
            console.print("[dim]  Add multiple hosts: /inventory quick-add host1,host2,host3[/dim]")
            return True

        # Parse arguments
        hostname_arg = args[0]
        ip_address = None
        environment = None

        # Check for comma-separated hostnames
        if ',' in hostname_arg:
            hostnames = [h.strip() for h in hostname_arg.split(',') if h.strip()]
            added = 0
            for hostname in hostnames:
                try:
                    self.repo.add_host(hostname=hostname, changed_by="user")
                    added += 1
                except Exception as e:
                    logger.debug(f"Failed to add {hostname}: {e}")
            print_success(f"Added {added}/{len(hostnames)} hosts")
            return True

        # Parse optional arguments
        i = 1
        while i < len(args):
            if args[i] == "--env" and i + 1 < len(args):
                environment = args[i + 1]
                i += 2
            elif not ip_address and not args[i].startswith("--"):
                ip_address = args[i]
                i += 1
            else:
                i += 1

        # Check if host exists
        existing = self.repo.get_host_by_name(hostname_arg)
        if existing:
            print_warning(f"Host '{hostname_arg}' already exists")
            return True

        # Add host
        try:
            host_id = self.repo.add_host(
                hostname=hostname_arg,
                ip_address=ip_address,
                environment=environment,
                changed_by="user",
            )
            print_success(f"✅ Added host '{hostname_arg}' (ID: {host_id})")
            if ip_address:
                console.print(f"  [dim]IP: {ip_address}[/dim]")
            if environment:
                console.print(f"  [dim]Environment: {environment}[/dim]")
            console.print("[dim]Use '/inventory ssh-key <host> set' to configure SSH key[/dim]")
        except Exception as e:
            print_error(f"Failed to add host: {e}")

        return True

    def _handle_setup_wizard(self) -> bool:
        """
        Interactive setup wizard for first-time users.

        Guides through:
        1. Adding first host
        2. Configuring SSH key
        3. Testing connection
        """
        from merlya.repl.ui import print_success, print_warning
        from merlya.security.ssh_credentials import check_key_needs_passphrase
        from pathlib import Path
        import getpass

        console.print("\n[bold cyan]🧙 Inventory Setup Wizard[/bold cyan]\n")
        console.print("Let's get you started with Merlya!\n")

        try:
            # Step 1: Check existing hosts
            stats = self.repo.get_stats()
            if stats.get("total_hosts", 0) > 0:
                console.print(f"✅ You already have {stats['total_hosts']} host(s) configured.")
                console.print("[dim]Use '/inventory show' to view them.[/dim]\n")
            else:
                console.print("[bold]Step 1: Add Your First Host[/bold]")
                hostname = input("Hostname or IP: ").strip()
                if hostname:
                    self.repo.add_host(hostname=hostname, changed_by="wizard")
                    print_success(f"Added: {hostname}")
                else:
                    print_warning("Skipped - no hostname provided")

            # Step 2: Configure SSH key
            console.print("\n[bold]Step 2: SSH Key Configuration[/bold]")

            # Check for existing SSH keys
            ssh_dir = Path.home() / ".ssh"
            default_keys = ["id_ed25519", "id_ecdsa", "id_rsa"]
            found_keys = []
            for key in default_keys:
                key_path = ssh_dir / key
                if key_path.exists():
                    found_keys.append(str(key_path))

            if found_keys:
                console.print(f"Found SSH key(s): {', '.join(Path(k).name for k in found_keys)}")
                use_default = input("Use default key for all hosts? (Y/n): ").strip().lower()

                if use_default != "n":
                    key_path = found_keys[0]  # Use first available
                    if self.repl:
                        from merlya.security.credentials import VariableType
                        self.repl.credential_manager.set_variable(
                            "ssh_key_global", key_path, VariableType.CONFIG
                        )
                        print_success(f"Global SSH key: {key_path}")

                        # Check if passphrase needed
                        if check_key_needs_passphrase(key_path, skip_validation=True):
                            console.print("[yellow]This key requires a passphrase.[/yellow]")
                            try:
                                passphrase = getpass.getpass("Enter passphrase (or press Enter to skip): ")
                                if passphrase:
                                    self.repl.credential_manager.set_variable(
                                        "ssh-passphrase-global", passphrase, VariableType.SECRET
                                    )
                                    print_success("Passphrase cached for this session")
                            except (KeyboardInterrupt, EOFError):
                                print_warning("Passphrase setup skipped")
            else:
                console.print("[dim]No default SSH keys found. You can configure them later.[/dim]")

            # Step 3: Summary
            console.print("\n[bold green]✅ Setup Complete![/bold green]\n")
            console.print("Quick commands:")
            console.print("  [cyan]list hosts[/cyan]          - Show your hosts to AI")
            console.print("  [cyan]scan @hostname[/cyan]      - Scan a host")
            console.print("  [cyan]/inventory show[/cyan]     - View inventory details")
            console.print()

        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Setup cancelled[/yellow]")

        return True

    def _show_help(self) -> bool:
        """Show inventory command help."""
        console.print("\n[bold cyan]Inventory Commands[/bold cyan]\n")

        console.print("[bold]Quick Start:[/bold]")
        console.print("  /inventory setup              Interactive setup wizard (recommended)")
        console.print("  /inventory quick-add <host>   Quickly add a host (minimal prompts)")
        console.print()

        console.print("[bold]Managing Hosts:[/bold]")
        console.print("  /inventory add <file>         Import hosts from file (CSV, JSON, YAML, etc.)")
        console.print("  /inventory add /etc/hosts     Import from system file")
        console.print("  /inventory add-host <name>    Add a single host with full options")
        console.print("  /inventory remove <source>    Remove an inventory source")
        console.print()

        console.print("[bold]Viewing Inventory:[/bold]")
        console.print("  /inventory list               List all inventory sources")
        console.print("  /inventory show [source]      Show hosts (optionally from specific source)")
        console.print("  /inventory search <pattern>   Search hosts by name/IP")
        console.print("  /inventory stats              Show inventory statistics")
        console.print()

        console.print("[bold]SSH Key Management:[/bold]")
        console.print("  /inventory ssh-key set <path>   Set global default SSH key")
        console.print("  /inventory ssh-key show         Show global SSH key config")
        console.print("  /inventory ssh-key <host> set   Set SSH key for specific host")
        console.print("  [dim]Passphrase: prompted on first use, cached for session[/dim]")
        console.print()

        console.print("[bold]Other:[/bold]")
        console.print("  /inventory export <file>      Export inventory to file")
        console.print("  /inventory snapshot [name]    Create inventory snapshot")
        console.print("  /inventory relations          Manage host relations")
        console.print()

        console.print("[bold]Using Hosts in Prompts:[/bold]")
        console.print("  Reference hosts with @: [cyan]check nginx on @web-prod-01[/cyan]")
        console.print("  Auto-completes from inventory (press Tab)")
        return True
