"""
SSH command handler - Centralized SSH key and connection management.

Handles: /ssh [subcommand]

This module consolidates all SSH-related functionality into a single command:
- SSH configuration overview
- Key management (global and per-host)
- Passphrase management
- SSH agent status
- Connection testing
"""
import getpass
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from rich.table import Table

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.ssh_credentials import (
    check_key_needs_passphrase,
    sanitize_path_for_log,
    validate_ssh_key_path,
)
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
        if not args:
            return self._show_overview()

        cmd = args[0].lower()
        cmd_args = args[1:]

        handlers = {
            "info": lambda: self._show_overview(),
            "keys": lambda: self._show_keys(),
            "agent": lambda: self._show_agent(),
            "key": lambda: self._handle_key(cmd_args),
            "host": lambda: self._handle_host(cmd_args),
            "passphrase": lambda: self._handle_passphrase(cmd_args),
            "test": lambda: self._handle_test(cmd_args),
            "help": lambda: self._show_help(),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                return handler()
            except Exception as e:
                logger.exception(f"SSH command error: {e}")
                print_error(f"Command failed: {e}")
                return True

        print_error(f"Unknown SSH subcommand: {cmd}")
        self._show_help()
        return True

    def _show_overview(self) -> bool:
        """Show comprehensive SSH configuration overview."""
        console.print("\n[bold cyan]🔐 SSH Configuration Overview[/bold cyan]\n")

        if not self.repl:
            print_warning("REPL context not available")
            return True

        credentials = self.repl.credentials

        # 1. SSH Agent Status
        console.print("[bold]SSH Agent[/bold]")
        if credentials.supports_agent():
            agent_keys = credentials.get_agent_keys()
            if agent_keys:
                console.print(f"  ✅ [green]ssh-agent running: {len(agent_keys)} key(s) loaded[/green]")
            else:
                console.print("  ⚠️ [yellow]ssh-agent detected but no keys loaded[/yellow]")
        else:
            console.print("  ❌ [dim]ssh-agent not available (SSH_AUTH_SOCK not set)[/dim]")

        # 2. Global Key Configuration
        console.print("\n[bold]Global SSH Key[/bold]")
        global_key = credentials.get_variable("ssh_key_global")
        if global_key:
            console.print(f"  📁 Path: [cyan]{global_key}[/cyan]")
            if Path(global_key).exists():
                console.print("  ✅ Status: [green]Key file exists[/green]")
                # Check passphrase status
                if check_key_needs_passphrase(global_key, skip_validation=True):
                    has_passphrase = credentials.get_variable("ssh-passphrase-global")
                    if has_passphrase:
                        console.print("  🔑 Passphrase: [green]Cached for session[/green]")
                    else:
                        console.print("  🔑 Passphrase: [yellow]Required (will prompt on use)[/yellow]")
                else:
                    console.print("  🔑 Passphrase: [dim]Not required[/dim]")
            else:
                console.print("  ❌ Status: [red]Key file not found[/red]")
        else:
            console.print("  [dim]Not configured[/dim]")
            # Show what default would be used
            default_key = credentials.get_default_key()
            if default_key:
                console.print(f"  [dim]Default key: {default_key}[/dim]")

        # 3. Available Keys Summary
        keys = credentials.get_ssh_keys()
        console.print(f"\n[bold]Available Keys[/bold]: {len(keys)} found in ~/.ssh")

        # 4. Key Resolution Priority
        console.print("\n[bold]Key Resolution Priority[/bold]")
        console.print("  1. Host-specific key (from inventory)")
        console.print("  2. Global key (/ssh key set)")
        console.print("  3. ~/.ssh/config IdentityFile")
        console.print("  4. Default keys (id_ed25519, id_rsa, etc.)")

        console.print("\n[dim]Use '/ssh help' for all commands[/dim]\n")
        return True

    def _show_keys(self) -> bool:
        """List all available SSH keys."""
        console.print("\n[bold]🔑 Available SSH Keys[/bold]\n")

        if not self.repl:
            print_warning("REPL context not available")
            return True

        credentials = self.repl.credentials
        keys = credentials.get_ssh_keys()

        if not keys:
            print_warning("No SSH keys found in ~/.ssh")
            console.print("[dim]Generate one with: ssh-keygen -t ed25519[/dim]")
            return True

        table = Table(show_header=True)
        table.add_column("Key File", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Encrypted", style="yellow")
        table.add_column("Status", style="green")

        global_key = credentials.get_variable("ssh_key_global")
        default_key = credentials.get_default_key()

        for key_path in keys:
            key_name = Path(key_path).name
            # Determine key type from filename
            if "ed25519" in key_name:
                key_type = "ED25519"
            elif "ecdsa" in key_name:
                key_type = "ECDSA"
            elif "rsa" in key_name:
                key_type = "RSA"
            elif "dsa" in key_name:
                key_type = "DSA"
            else:
                key_type = "Unknown"

            # Check if encrypted
            try:
                encrypted = "Yes" if check_key_needs_passphrase(key_path, skip_validation=True) else "No"
            except Exception:
                encrypted = "?"

            # Determine status
            status = ""
            if key_path == global_key:
                status = "[bold green]Global Default[/bold green]"
            elif key_path == default_key:
                status = "[green]Auto-default[/green]"
            else:
                status = "[dim]-[/dim]"

            table.add_row(key_name, key_type, encrypted, status)

        console.print(table)
        console.print()
        return True

    def _show_agent(self) -> bool:
        """Show detailed ssh-agent information."""
        console.print("\n[bold]🔐 SSH Agent Status[/bold]\n")

        if not self.repl:
            print_warning("REPL context not available")
            return True

        credentials = self.repl.credentials

        if not credentials.supports_agent():
            print_warning("ssh-agent not available")
            console.print("\n[dim]To enable ssh-agent:[/dim]")
            console.print("  eval $(ssh-agent)")
            console.print("  ssh-add ~/.ssh/id_ed25519")
            return True

        agent_keys = credentials.get_agent_keys()
        if agent_keys:
            console.print(f"✅ [green]Agent running with {len(agent_keys)} key(s)[/green]\n")

            table = Table(show_header=True)
            table.add_column("#", style="dim")
            table.add_column("Key", style="cyan")

            for i, key in enumerate(agent_keys, 1):
                table.add_row(str(i), key)

            console.print(table)
        else:
            console.print("⚠️ [yellow]Agent running but no keys loaded[/yellow]")
            console.print("\n[dim]Add keys with: ssh-add ~/.ssh/id_ed25519[/dim]")

        console.print()
        return True

    def _handle_key(self, args: List[str]) -> bool:
        """Handle /ssh key subcommands."""
        if not args:
            return self._show_global_key()

        subcmd = args[0].lower()

        if subcmd == "set":
            return self._set_global_key(args[1:])
        elif subcmd == "show":
            return self._show_global_key()
        elif subcmd == "clear":
            return self._clear_global_key()
        else:
            # Treat as path: /ssh key ~/.ssh/id_rsa -> set that key
            return self._set_global_key(args)

    def _show_global_key(self) -> bool:
        """Show global SSH key configuration."""
        console.print("\n[bold]🔑 Global SSH Key Configuration[/bold]\n")

        if not self.repl:
            print_warning("REPL context not available")
            return True

        credentials = self.repl.credentials
        global_key = credentials.get_variable("ssh_key_global")

        if global_key:
            console.print(f"  Path: [cyan]{global_key}[/cyan]")
            if Path(global_key).exists():
                console.print("  Status: [green]Key file exists[/green]")
                if check_key_needs_passphrase(global_key, skip_validation=True):
                    has_passphrase = credentials.get_variable("ssh-passphrase-global")
                    if has_passphrase:
                        console.print("  Passphrase: [green]Cached for session[/green]")
                    else:
                        console.print("  Passphrase: [yellow]Required (will prompt)[/yellow]")
                else:
                    console.print("  Passphrase: [dim]Not required[/dim]")
            else:
                console.print("  Status: [red]Key file not found[/red]")
        else:
            console.print("  [dim]Not configured[/dim]")
            default_key = credentials.get_default_key()
            if default_key:
                console.print(f"\n  [dim]Current auto-default: {default_key}[/dim]")

        console.print()
        return True

    def _set_global_key(self, args: List[str]) -> bool:
        """Set global default SSH key."""
        if not args:
            print_error("Usage: /ssh key set <path>")
            console.print("[dim]Example: /ssh key set ~/.ssh/id_ed25519[/dim]")
            return True

        if not self.repl:
            print_warning("REPL context not available")
            return True

        key_path = args[0]
        expanded_path = Path(key_path).expanduser().resolve()

        # Validate key file exists
        if not expanded_path.exists():
            print_error(f"Key file not found: {expanded_path}")
            return True

        if not expanded_path.is_file():
            print_error(f"Not a file: {expanded_path}")
            return True

        # Store in CONFIG variable
        from merlya.security.credentials import VariableType
        self.repl.credential_manager.set_variable(
            "ssh_key_global", str(expanded_path), VariableType.CONFIG
        )
        print_success(f"Global SSH key set to: {expanded_path}")

        # Check if key needs passphrase
        key_needs_passphrase = check_key_needs_passphrase(str(expanded_path), skip_validation=True)

        if key_needs_passphrase:
            console.print("[yellow]This key requires a passphrase.[/yellow]")
            try:
                set_now = input("Set passphrase now? (Y/n): ").strip().lower()
                if set_now != "n":
                    passphrase = getpass.getpass("SSH key passphrase (hidden): ")
                    if passphrase:
                        self.repl.credential_manager.set_variable(
                            "ssh-passphrase-global", passphrase, VariableType.SECRET
                        )
                        print_success("✅ Passphrase cached for this session")
                    else:
                        print_warning("Empty passphrase, skipping")
            except (KeyboardInterrupt, EOFError):
                print_warning("\nPassphrase setup skipped")
        else:
            console.print("[dim]Key does not require a passphrase.[/dim]")

        console.print("[dim]This key will be used for hosts without specific config.[/dim]")
        return True

    def _clear_global_key(self) -> bool:
        """Clear global SSH key configuration."""
        if not self.repl:
            print_warning("REPL context not available")
            return True

        self.repl.credential_manager.delete_variable("ssh_key_global")
        self.repl.credential_manager.delete_variable("ssh-passphrase-global")
        print_success("Global SSH key configuration cleared")
        return True

    def _handle_host(self, args: List[str]) -> bool:
        """Handle /ssh host <hostname> subcommands."""
        if not args:
            print_error("Usage: /ssh host <hostname> [show|set|clear]")
            return True

        hostname = args[0]
        subcmd = args[1].lower() if len(args) > 1 else "show"

        if subcmd == "show":
            return self._show_host_config(hostname)
        elif subcmd == "set":
            return self._set_host_key(hostname)
        elif subcmd == "clear":
            return self._clear_host_config(hostname)
        else:
            print_error(f"Unknown subcommand: {subcmd}")
            console.print("[dim]Use: show, set, or clear[/dim]")
            return True

    def _show_host_config(self, hostname: str) -> bool:
        """Show SSH configuration for a specific host."""
        console.print(f"\n[bold]🔑 SSH Configuration for {hostname}[/bold]\n")

        if not self.repo:
            print_warning("Inventory not available")
            return True

        host = self.repo.get_host_by_name(hostname)
        if not host:
            print_warning(f"Host '{hostname}' not found in inventory")
            console.print("[dim]Add it first with: /inventory add-host[/dim]")
            return True

        metadata = host.get("metadata", {}) or {}
        ssh_key_path = metadata.get("ssh_key_path")
        ssh_passphrase_secret = metadata.get("ssh_passphrase_secret")

        if ssh_key_path:
            console.print(f"  Key path: [cyan]{ssh_key_path}[/cyan]")
            if Path(ssh_key_path).expanduser().exists():
                console.print("  Status: [green]Key file exists[/green]")
            else:
                console.print("  Status: [red]Key file not found[/red]")
        else:
            console.print("  Key path: [dim]Not configured (using global/default)[/dim]")

        if ssh_passphrase_secret:
            if self.repl and self.repl.credential_manager.get_variable(ssh_passphrase_secret):
                console.print(f"  Passphrase: [green]Cached as @{ssh_passphrase_secret}[/green]")
            else:
                console.print(f"  Passphrase: [yellow]Configured but not cached (@{ssh_passphrase_secret})[/yellow]")
        else:
            console.print("  Passphrase: [dim]Not configured[/dim]")

        # Show what would actually be used
        if self.repl:
            key_path, passphrase, source = self.repl.credentials.resolve_ssh_for_host(
                hostname, prompt_passphrase=False
            )
            if key_path:
                console.print(f"\n  [dim]Effective key: {key_path} (from {source})[/dim]")

        console.print()
        return True

    def _set_host_key(self, hostname: str) -> bool:
        """Set SSH key for a specific host."""
        if not self.repo:
            print_warning("Inventory not available")
            return True

        host = self.repo.get_host_by_name(hostname)
        if not host:
            print_warning(f"Host '{hostname}' not found in inventory")
            console.print("[dim]Add it first with: /inventory add-host[/dim]")
            return True

        if not self.repl:
            print_warning("REPL context not available")
            return True

        metadata = host.get("metadata", {}) or {}

        try:
            # Prompt for SSH key
            current_key = metadata.get("ssh_key_path", "")
            prompt = f"SSH key path [{current_key}]: " if current_key else "SSH key path: "
            ssh_key_path = input(prompt).strip()

            if not ssh_key_path and current_key:
                ssh_key_path = current_key

            if not ssh_key_path:
                print_error("SSH key path is required")
                return True

            # Expand and validate
            expanded_path = Path(ssh_key_path).expanduser()
            if not expanded_path.exists():
                print_warning(f"SSH key not found at: {expanded_path}")
                confirm = input("Continue anyway? (y/N): ").strip().lower()
                if confirm != "y":
                    return True

            # Update metadata
            metadata["ssh_key_path"] = str(expanded_path)

            # Ask about passphrase
            has_passphrase = input("Set/update passphrase? (y/N): ").strip().lower()
            if has_passphrase == "y":
                secret_key = f"ssh-passphrase-{hostname}"
                passphrase = getpass.getpass("SSH key passphrase (hidden): ")

                if passphrase:
                    from merlya.security.credentials import VariableType
                    self.repl.credential_manager.set_variable(
                        secret_key, passphrase, VariableType.SECRET
                    )
                    metadata["ssh_passphrase_secret"] = secret_key
                    print_success(f"Passphrase stored as secret: @{secret_key}")

            # Update host in inventory
            self.repo.add_host(
                hostname=hostname,
                metadata=metadata,
                changed_by="user",
            )
            print_success(f"SSH key configured for {hostname}")

        except (KeyboardInterrupt, EOFError):
            print_warning("\nCancelled")

        return True

    def _clear_host_config(self, hostname: str) -> bool:
        """Clear SSH configuration for a specific host."""
        if not self.repo:
            print_warning("Inventory not available")
            return True

        host = self.repo.get_host_by_name(hostname)
        if not host:
            print_warning(f"Host '{hostname}' not found in inventory")
            return True

        metadata = host.get("metadata", {}) or {}

        # Clear SSH config
        if "ssh_key_path" in metadata:
            del metadata["ssh_key_path"]

        # Also clear passphrase secret if exists
        secret_key = metadata.pop("ssh_passphrase_secret", None)
        if secret_key and self.repl:
            self.repl.credential_manager.delete_variable(secret_key)
            console.print(f"  [dim]Cleared secret: @{secret_key}[/dim]")

        self.repo.add_host(
            hostname=hostname,
            metadata=metadata,
            changed_by="user",
        )
        print_success(f"SSH configuration cleared for {hostname}")
        return True

    def _handle_passphrase(self, args: List[str]) -> bool:
        """Handle passphrase management."""
        if not args:
            print_error("Usage: /ssh passphrase <key_name_or_path>")
            console.print("[dim]Example: /ssh passphrase id_ed25519[/dim]")
            console.print("[dim]Example: /ssh passphrase global[/dim]")
            return True

        if not self.repl:
            print_warning("REPL context not available")
            return True

        key_ref = args[0]

        # Determine secret key name
        if key_ref.lower() == "global":
            secret_key = "ssh-passphrase-global"
            display_name = "global key"
        elif "/" in key_ref or key_ref.startswith("~"):
            # Full path provided
            key_name = Path(key_ref).name
            secret_key = f"ssh-passphrase-{key_name}"
            display_name = key_name
        else:
            # Just key name (e.g., id_ed25519)
            secret_key = f"ssh-passphrase-{key_ref}"
            display_name = key_ref

        # Check if already cached
        existing = self.repl.credential_manager.get_variable(secret_key)
        if existing:
            console.print(f"Passphrase for [cyan]{display_name}[/cyan] is already cached.")
            update = input("Update it? (y/N): ").strip().lower()
            if update != "y":
                return True

        try:
            passphrase = getpass.getpass(f"Enter passphrase for {display_name} (hidden): ")
            if passphrase:
                from merlya.security.credentials import VariableType
                self.repl.credential_manager.set_variable(
                    secret_key, passphrase, VariableType.SECRET
                )
                print_success(f"✅ Passphrase cached for session (stored as @{secret_key})")
            else:
                print_warning("Empty passphrase, not saved")
        except (KeyboardInterrupt, EOFError):
            print_warning("\nCancelled")

        return True

    def _handle_test(self, args: List[str]) -> bool:
        """Test SSH connection to a host."""
        if not args:
            print_error("Usage: /ssh test <hostname>")
            return True

        hostname = args[0]
        console.print(f"\n[bold]🔌 Testing SSH connection to {hostname}[/bold]\n")

        if not self.repl:
            print_warning("REPL context not available")
            return True

        # Resolve credentials
        credentials = self.repl.credentials
        key_path, passphrase, source = credentials.resolve_ssh_for_host(
            hostname, prompt_passphrase=True
        )

        console.print(f"  Key: [cyan]{sanitize_path_for_log(key_path) if key_path else 'None'}[/cyan] (from {source or 'none'})")
        console.print(f"  Passphrase: {'[green]provided[/green]' if passphrase else '[dim]not set[/dim]'}")

        # Get user
        user = credentials.get_user_for_host(hostname)
        console.print(f"  User: [cyan]{user}[/cyan]")

        # Try connection
        try:
            from merlya.executors.ssh import SSHManager

            ssh_manager = SSHManager()
            console.print("\n  Connecting...")

            success = ssh_manager.test_connection(hostname, user=user)

            if success:
                print_success(f"\n✅ Connection to {hostname} successful!")
            else:
                print_error(f"\n❌ Connection to {hostname} failed")
                console.print("[dim]Check hostname, credentials, and network access[/dim]")

        except ImportError:
            print_warning("SSH manager not available")
        except Exception as e:
            print_error(f"Connection test failed: {e}")

        return True

    def _show_help(self) -> bool:
        """Show SSH command help."""
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
