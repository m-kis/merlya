"""
Main SSH command handler that dispatches to sub-handlers.
"""
from typing import List, Optional, TYPE_CHECKING
from merlya.repl.ui import print_error
from merlya.utils.logger import logger

if TYPE_CHECKING:
    from merlya.repl.core import MerlyaREPL

class SSHCommandHandler:
    """
    Handles /ssh commands for centralized SSH management.

    Commands:
        /ssh                     - Show SSH overview (info + agent + global key)
        /ssh info                - Same as /ssh
        /ssh keys                - List available SSH keys
        /ssh agent               - Show ssh-agent status and loaded keys
        /ssh key set <path>      - Set global default SSH key
        /ssh key show            - Show global SSH key configuration
        /ssh key clear           - Clear global SSH key
        /ssh host <name> show    - Show SSH config for specific host
        /ssh host <name> set     - Set SSH key for specific host
        /ssh host <name> clear   - Clear SSH config for specific host
        /ssh passphrase <key>    - Set passphrase for a key
        /ssh test <hostname>     - Test SSH connection to host
    """

    def __init__(self, repl: Optional["MerlyaREPL"] = None):
        """Initialize with reference to the REPL instance."""
        self.repl = repl
        self._repo = None

    @property
    def repo(self):
        """Lazy load inventory repository."""
        if self._repo is None:
            try:
                from merlya.memory.persistence.inventory_repository import (
                    get_inventory_repository,
                )
                self._repo = get_inventory_repository()
            except Exception as e:
                logger.debug(f"Could not load inventory repository: {e}")
        return self._repo

    def handle(self, args: List[str]) -> bool:
        """
        Handle /ssh command.

        Returns True to indicate the REPL should continue.
        """
        from merlya.repl.commands.ssh.agent import show_agent
        from merlya.repl.commands.ssh.keys import show_keys, handle_key, show_overview
        from merlya.repl.commands.ssh.hosts import handle_host
        from merlya.repl.commands.ssh.passphrase import handle_passphrase
        from merlya.repl.commands.ssh.test import handle_test

        if not args:
            return show_overview(self)

        cmd = args[0].lower()
        cmd_args = args[1:]

        handlers = {
            "info": lambda: show_overview(self),
            "keys": lambda: show_keys(self),
            "agent": lambda: show_agent(self),
            "key": lambda: handle_key(self, cmd_args),
            "host": lambda: handle_host(self, cmd_args),
            "passphrase": lambda: handle_passphrase(self, cmd_args),
            "test": lambda: handle_test(self, cmd_args),
            "help": lambda: self._show_help(),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                return handler()
            except (KeyboardInterrupt, SystemExit):
                raise  # Don't suppress these
            except FileNotFoundError as e:
                print_error(f"File not found: {e}")
                return True
            except PermissionError as e:
                print_error(f"Permission denied: {e}")
                return True
            except Exception as e:
                logger.exception(f"SSH command error: {e}")
                print_error(f"Unexpected error: {e}")
                return True

        print_error(f"Unknown SSH subcommand: {cmd}")
        self._show_help()
        return True

    def _show_help(self) -> bool:
        """Show SSH command help."""
        from merlya.repl.ui import console
        console.print("\n[bold cyan]SSH Commands[/bold cyan]\n")

        console.print("[bold]Overview:[/bold]")
        console.print("  /ssh                           Show SSH configuration overview")
        console.print("  /ssh info                      Same as /ssh")
        console.print("  /ssh keys                      List available SSH keys")
        console.print("  /ssh agent                     Show ssh-agent status")
        console.print()

        console.print("[bold]Global Key Management:[/bold]")
        console.print("  /ssh key set <path>            Set global default SSH key")
        console.print("  /ssh key show                  Show global key configuration")
        console.print("  /ssh key clear                 Clear global key")
        console.print()

        console.print("[bold]Per-Host Key Management:[/bold]")
        console.print("  /ssh host <name> show          Show SSH config for host")
        console.print("  /ssh host <name> set           Set SSH key for host (interactive)")
        console.print("  /ssh host <name> clear         Clear SSH config for host")
        console.print()

        console.print("[bold]Passphrase Management:[/bold]")
        console.print("  /ssh passphrase global         Cache passphrase for global key")
        console.print("  /ssh passphrase <key_name>     Cache passphrase for specific key")
        console.print()

        console.print("[bold]Testing:[/bold]")
        console.print("  /ssh test <hostname>           Test SSH connection to host")
        console.print()

        console.print("[bold]Key Resolution Priority:[/bold]")
        console.print("  1. Host-specific key (from inventory metadata)")
        console.print("  2. Global key (/ssh key set)")
        console.print("  3. ~/.ssh/config IdentityFile")
        console.print("  4. Default keys (id_ed25519, id_rsa, etc.)")
        console.print()

        console.print("[dim]Passphrases are cached in memory only and expire on exit.[/dim]")
        return True
