"""
Handles management commands (remove, export, snapshot, add-host, ssh-key).
"""
import csv
import getpass
import json
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from athena_ai.repl.ui import console, print_error, print_success, print_warning

if TYPE_CHECKING:
    from athena_ai.memory.persistence.inventory_repository import InventoryRepository
    from athena_ai.repl.core import AthenaREPL


class InventoryManager:
    """Handles management of inventory sources and data."""

    def __init__(self, repo: "InventoryRepository"):
        self.repo = repo

    def handle_remove(self, args: List[str]) -> bool:
        """Handle /inventory remove <source>."""
        if not args:
            print_error("Usage: /inventory remove <source_name>")
            return True

        source_name = args[0]
        source = self.repo.get_source(source_name)

        if not source:
            print_error(f"Source not found: {source_name}")
            return True

        # Confirm deletion
        host_count = source.get("host_count", 0)
        try:
            confirm = input(f"Delete '{source_name}' and its {host_count} hosts? (y/N): ").strip().lower()
            if confirm != "y":
                print_warning("Deletion cancelled")
                return True
        except (KeyboardInterrupt, EOFError):
            print_warning("\nDeletion cancelled")
            return True

        if self.repo.delete_source(source_name):
            print_success(f"Removed inventory source: {source_name}")
        else:
            print_error("Failed to remove source")

        return True

    def handle_export(self, args: List[str]) -> bool:
        """Handle /inventory export <file>."""
        if not args:
            print_error("Usage: /inventory export <file_path>")
            return True

        file_path = Path(" ".join(args)).expanduser()

        # Determine format from extension
        ext = file_path.suffix.lower()
        if ext not in [".json", ".csv", ".yaml", ".yml"]:
            print_error("Supported export formats: .json, .csv, .yaml, .yml")
            return True

        hosts = self.repo.get_all_hosts()
        if not hosts:
            print_warning("No hosts to export")
            return True

        try:
            if ext == ".json":
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(hosts, f, indent=2, default=str, ensure_ascii=False)

            elif ext == ".csv":
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        "hostname", "ip_address", "environment", "groups", "role", "service"
                    ])
                    writer.writeheader()
                    for host in hosts:
                        writer.writerow({
                            "hostname": host.get("hostname", ""),
                            "ip_address": host.get("ip_address", ""),
                            "environment": host.get("environment", ""),
                            "groups": json.dumps(host.get("groups", [])),
                            "role": host.get("role", ""),
                            "service": host.get("service", ""),
                        })

            elif ext in [".yaml", ".yml"]:
                try:
                    import yaml
                except ImportError:
                    print_error("YAML export requires PyYAML: pip install pyyaml")
                    return True
                with open(file_path, "w", encoding="utf-8") as f:
                    yaml.dump(hosts, f, default_flow_style=False, allow_unicode=True)

            print_success(f"Exported {len(hosts)} hosts to {file_path}")

        except PermissionError:
            print_error(f"Permission denied: {file_path}")
        except OSError as e:
            print_error(f"Export failed: {e}")

        return True

    def handle_add_host(self, args: List[str], repl: Optional["AthenaREPL"] = None) -> bool:
        """
        Handle /inventory add-host - Interactive single host addition.

        Usage: /inventory add-host [hostname]

        Prompts for:
        - hostname (if not provided)
        - IP address (optional)
        - environment (optional)
        - groups (optional, comma-separated)
        - SSH key path (optional)
        - SSH key passphrase (optional, stored as secret)
        """
        # Get hostname
        if args:
            hostname = args[0]
        else:
            try:
                hostname = input("Hostname: ").strip()
                if not hostname:
                    print_error("Hostname is required")
                    return True
            except (KeyboardInterrupt, EOFError):
                print_warning("\nCancelled")
                return True

        # Check if host already exists
        existing = self.repo.get_host_by_name(hostname)
        if existing:
            print_warning(f"Host '{hostname}' already exists. Use /inventory ssh-key to update SSH config.")
            return True

        try:
            # Prompt for optional fields
            ip_address = input("IP address (optional): ").strip() or None
            environment = input("Environment (e.g., production, staging): ").strip() or None
            groups_str = input("Groups (comma-separated, optional): ").strip()
            groups = [g.strip() for g in groups_str.split(",") if g.strip()] if groups_str else None

            # SSH key configuration
            ssh_key_path = input("SSH key path (optional, e.g., ~/.ssh/id_ed25519): ").strip()
            ssh_key_passphrase_secret = None

            if ssh_key_path:
                # Expand and validate path
                expanded_path = Path(ssh_key_path).expanduser()
                if not expanded_path.exists():
                    print_warning(f"SSH key not found at: {expanded_path}")
                    confirm = input("Continue anyway? (y/N): ").strip().lower()
                    if confirm != "y":
                        print_warning("Cancelled")
                        return True

                # Ask about passphrase
                has_passphrase = input("Does this key have a passphrase? (y/N): ").strip().lower()
                if has_passphrase == "y":
                    # Store passphrase as a secret
                    secret_key = f"ssh-passphrase-{hostname}"
                    passphrase = getpass.getpass("SSH key passphrase (hidden): ")

                    if passphrase and repl:
                        # Store in secrets system
                        from athena_ai.security.credentials import VariableType
                        repl.credential_manager.set_variable(
                            secret_key, passphrase, VariableType.SECRET
                        )
                        ssh_key_passphrase_secret = secret_key
                        print_success(f"Passphrase stored as secret: @{secret_key}")

            # Build metadata with SSH info
            metadata = {}
            if ssh_key_path:
                metadata["ssh_key_path"] = str(Path(ssh_key_path).expanduser())
            if ssh_key_passphrase_secret:
                metadata["ssh_passphrase_secret"] = ssh_key_passphrase_secret

            # Add host to inventory
            host_id = self.repo.add_host(
                hostname=hostname,
                ip_address=ip_address,
                environment=environment,
                groups=groups,
                metadata=metadata if metadata else None,
                changed_by="user",
            )

            print_success(f"Added host '{hostname}' (ID: {host_id})")
            if ssh_key_path:
                console.print(f"  [dim]SSH key: {ssh_key_path}[/dim]")
            if ssh_key_passphrase_secret:
                console.print(f"  [dim]Passphrase secret: @{ssh_key_passphrase_secret}[/dim]")

        except (KeyboardInterrupt, EOFError):
            print_warning("\nCancelled")

        return True

    def handle_ssh_key(self, args: List[str], repl: Optional["AthenaREPL"] = None) -> bool:
        """
        Handle /inventory ssh-key - Manage SSH keys for hosts.

        Usage:
            /inventory ssh-key                      - Show usage and global config
            /inventory ssh-key set <path>           - Set global default SSH key
            /inventory ssh-key show                 - Show global SSH config
            /inventory ssh-key clear                - Clear global SSH key
            /inventory ssh-key <hostname> set       - Set SSH key for specific host
            /inventory ssh-key <hostname> show      - Show SSH config for host
            /inventory ssh-key <hostname> clear     - Remove SSH key config
        """
        if not args:
            self._show_ssh_key_help(repl)
            return True

        # Handle implicit global context (e.g. "set <path>" -> "global set <path>")
        if args[0].lower() in ["set", "clear", "show"] and args[0].lower() != "global":
            args.insert(0, "global")

        hostname = args[0]
        subcmd = args[1].lower() if len(args) > 1 else "show"

        # Handle global SSH key
        if hostname.lower() == "global":
            if subcmd == "set":
                if len(args) < 3:
                    print_error("Usage: /inventory ssh-key set <path>")
                    return True
                key_path = args[2]
                expanded_path = Path(key_path).expanduser()

                # Validate key file
                if not expanded_path.exists():
                    print_warning(f"Key file not found: {expanded_path}")
                    try:
                        confirm = input("Continue anyway? (y/N): ").strip().lower()
                        if confirm != "y":
                            return True
                    except (KeyboardInterrupt, EOFError):
                        print_warning("\nCancelled")
                        return True

                # Store in special variable
                if repl:
                    from athena_ai.security.credentials import VariableType
                    repl.credential_manager.set_variable(
                        "ssh_key_global", str(expanded_path), VariableType.CONFIG
                    )
                    print_success(f"Global SSH key set to: {expanded_path}")

                    # Check if key needs passphrase and offer to set it
                    if repl.credential_manager._key_needs_passphrase(str(expanded_path)):
                        console.print("[dim]This key appears to be encrypted.[/dim]")
                        try:
                            set_now = input("Set passphrase now? (Y/n): ").strip().lower()
                            if set_now != "n":
                                secret_key = "ssh-passphrase-global"
                                passphrase = getpass.getpass("SSH key passphrase (hidden): ")

                                if passphrase:
                                    repl.credential_manager.set_variable(
                                        secret_key, passphrase, VariableType.SECRET
                                    )
                                    print_success("Passphrase cached (session only, not persisted)")
                        except (KeyboardInterrupt, EOFError):
                            print_warning("\nPassphrase setup skipped")
                            console.print("[dim]Passphrase will be prompted on first SSH connection.[/dim]")

                    console.print("[dim]This key will be used for hosts without specific config.[/dim]")

            elif subcmd == "show":
                self._show_global_ssh_config(repl)

            elif subcmd == "clear":
                if repl:
                    repl.credential_manager.delete_variable("ssh_key_global")
                    repl.credential_manager.delete_variable("ssh-passphrase-global")
                    print_success("Global SSH key cleared")
            else:
                print_error(f"Unknown subcommand: {subcmd}")
                console.print("[dim]Use: set <path>, show, or clear[/dim]")
            return True

        # Get host
        host = self.repo.get_host_by_name(hostname)
        if not host:
            print_error(f"Host not found: {hostname}")
            return True

        metadata = host.get("metadata", {}) or {}

        if subcmd == "show":
            # Display current SSH config
            ssh_key_path = metadata.get("ssh_key_path")
            ssh_passphrase_secret = metadata.get("ssh_passphrase_secret")

            console.print(f"\n[bold]🔑 SSH Configuration for {hostname}[/bold]\n")
            if ssh_key_path:
                console.print(f"  Key path: [cyan]{ssh_key_path}[/cyan]")
                # Check if file exists
                if Path(ssh_key_path).expanduser().exists():
                    console.print("  Status: [green]Key file exists[/green]")
                else:
                    console.print("  Status: [red]Key file not found[/red]")
            else:
                console.print("  Key path: [dim]Not configured[/dim]")

            if ssh_passphrase_secret:
                console.print(f"  Passphrase: [yellow]Stored as @{ssh_passphrase_secret}[/yellow]")
            else:
                console.print("  Passphrase: [dim]Not configured[/dim]")
            console.print()

        elif subcmd == "set":
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

                    if passphrase and repl:
                        from athena_ai.security.credentials import VariableType
                        repl.credential_manager.set_variable(
                            secret_key, passphrase, VariableType.SECRET
                        )
                        metadata["ssh_passphrase_secret"] = secret_key
                        print_success(f"Passphrase stored as secret: @{secret_key}")

                # Update host
                self.repo.add_host(
                    hostname=hostname,
                    metadata=metadata,
                    changed_by="user",
                )
                print_success(f"SSH key configured for {hostname}")

            except (KeyboardInterrupt, EOFError):
                print_warning("\nCancelled")

        elif subcmd == "clear":
            # Clear SSH config
            if "ssh_key_path" in metadata:
                del metadata["ssh_key_path"]

            # Also clear passphrase secret if exists
            secret_key = metadata.pop("ssh_passphrase_secret", None)
            if secret_key and repl:
                repl.credential_manager.delete_variable(secret_key)
                console.print(f"  [dim]Cleared secret: @{secret_key}[/dim]")

            self.repo.add_host(
                hostname=hostname,
                metadata=metadata,
                changed_by="user",
            )
            print_success(f"SSH configuration cleared for {hostname}")

        else:
            print_error(f"Unknown subcommand: {subcmd}")
            console.print("[dim]Use: show, set, or clear[/dim]")

        return True

    def _show_ssh_key_help(self, repl: Optional["AthenaREPL"] = None) -> None:
        """Show SSH key command help and current global config."""
        console.print("\n[bold cyan]SSH Key Management[/bold cyan]\n")
        console.print("[bold]Global Key (used for all hosts without specific config):[/bold]")
        console.print("  /inventory ssh-key set <path>      Set global default SSH key")
        console.print("  /inventory ssh-key show            Show global SSH key config")
        console.print("  /inventory ssh-key clear           Clear global SSH key")
        console.print()
        console.print("[bold]Host-specific Key:[/bold]")
        console.print("  /inventory ssh-key <host> set      Set SSH key for specific host")
        console.print("  /inventory ssh-key <host> show     Show SSH key config for host")
        console.print("  /inventory ssh-key <host> clear    Clear SSH key config for host")
        console.print()
        console.print("[bold]Key Resolution Priority:[/bold]")
        console.print("  1. Host-specific key (from inventory metadata)")
        console.print("  2. Global key (/inventory ssh-key set)")
        console.print("  3. ~/.ssh/config IdentityFile")
        console.print("  4. Default keys (id_ed25519, id_rsa, etc.)")
        console.print()
        console.print("[dim]Passphrase: prompted on first use, cached for session (not persisted)[/dim]")

        # Show current global config
        if repl:
            console.print()
            self._show_global_ssh_config(repl)

    def _show_global_ssh_config(self, repl: Optional["AthenaREPL"] = None) -> None:
        """Show current global SSH key configuration."""
        console.print("[bold]🔑 Global SSH Key Configuration[/bold]")

        if not repl:
            console.print("  [dim]Not available (no REPL context)[/dim]")
            return

        global_key = repl.credential_manager.get_variable("ssh_key_global")
        if global_key:
            console.print(f"  Key path: [cyan]{global_key}[/cyan]")
            if Path(global_key).exists():
                console.print("  Status: [green]Key file exists[/green]")
                # Check if encrypted
                if repl.credential_manager._key_needs_passphrase(global_key):
                    has_passphrase = repl.credential_manager.get_variable("ssh-passphrase-global")
                    if has_passphrase:
                        console.print("  Passphrase: [green]Cached for session[/green]")
                    else:
                        console.print("  Passphrase: [yellow]Required (will prompt on use)[/yellow]")
                else:
                    console.print("  Passphrase: [dim]Not required[/dim]")
            else:
                console.print("  Status: [red]Key file not found[/red]")
        else:
            console.print("  [dim]Not configured[/dim]")
            # Show what default key would be used
            default_key = repl.credential_manager.get_default_key()
            if default_key:
                console.print(f"  [dim]Default key: {default_key}[/dim]")

    def handle_snapshot(self, args: List[str]) -> bool:
        """Handle /inventory snapshot [name]."""
        name = args[0] if args else None

        try:
            snapshot_id = self.repo.create_snapshot(name=name)
            stats = self.repo.get_stats()

            print_success(f"Created snapshot #{snapshot_id}")
            console.print(f"  Hosts: {stats.get('total_hosts', 0)}")
            console.print(f"  Relations: {stats.get('total_relations', 0)}")
        except Exception as e:
            print_error(f"Failed to create snapshot: {e}")

        return True
