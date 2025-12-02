"""
SSH keys command handler.
"""
import getpass
from pathlib import Path
from typing import List

from rich.table import Table

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.credentials import VariableType
from merlya.security.ssh_credentials import check_key_needs_passphrase, validate_ssh_key_path

# Constants for secret key naming
SSH_KEY_GLOBAL = "ssh_key_global"
SSH_PASSPHRASE_GLOBAL = "ssh-passphrase-global"
MAX_INPUT_LENGTH = 256
MAX_PASSPHRASE_LENGTH = 1024

def show_overview(handler) -> bool:
    """Show comprehensive SSH configuration overview."""
    console.print("\n[bold cyan]🔐 SSH Configuration Overview[/bold cyan]\n")

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    credentials = handler.repl.credentials

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
    global_key = credentials.get_variable(SSH_KEY_GLOBAL)
    if global_key:
        console.print(f"  📁 Path: [cyan]{global_key}[/cyan]")
        if Path(global_key).exists():
            console.print("  ✅ Status: [green]Key file exists[/green]")
            # Check passphrase status
            if check_key_needs_passphrase(global_key, skip_validation=True):
                has_passphrase = credentials.get_variable(SSH_PASSPHRASE_GLOBAL)
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

def show_keys(handler) -> bool:
    """List all available SSH keys."""
    console.print("\n[bold]🔑 Available SSH Keys[/bold]\n")

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    credentials = handler.repl.credentials
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

    global_key = credentials.get_variable(SSH_KEY_GLOBAL)
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

def handle_key(handler, args: List[str]) -> bool:
    """Handle /ssh key subcommands."""
    if not args:
        return show_global_key(handler)

    subcmd = args[0].lower()

    if subcmd == "set":
        return set_global_key(handler, args[1:])
    elif subcmd == "show":
        return show_global_key(handler)
    elif subcmd == "clear":
        return clear_global_key(handler)
    else:
        # Treat as path: /ssh key ~/.ssh/id_rsa -> set that key
        return set_global_key(handler, args)

def show_global_key(handler) -> bool:
    """Show global SSH key configuration."""
    console.print("\n[bold]🔑 Global SSH Key Configuration[/bold]\n")

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    credentials = handler.repl.credentials
    global_key = credentials.get_variable(SSH_KEY_GLOBAL)

    if global_key:
        console.print(f"  Path: [cyan]{global_key}[/cyan]")
        if Path(global_key).exists():
            console.print("  Status: [green]Key file exists[/green]")
            if check_key_needs_passphrase(global_key, skip_validation=True):
                has_passphrase = credentials.get_variable(SSH_PASSPHRASE_GLOBAL)
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

def set_global_key(handler, args: List[str]) -> bool:
    """Set global default SSH key."""
    if not args:
        print_error("Usage: /ssh key set <path>")
        console.print("[dim]Example: /ssh key set ~/.ssh/id_ed25519[/dim]")
        return True

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    key_path = args[0]

    # Input validation
    if len(key_path) > MAX_INPUT_LENGTH:
        print_error("Path too long")
        return True

    expanded_path = Path(key_path).expanduser().resolve()

    # Validate key file exists
    if not expanded_path.exists():
        print_error(f"Key file not found: {expanded_path}")
        return True

    if not expanded_path.is_file():
        print_error(f"Not a file: {expanded_path}")
        return True

    # Validate path security before storage
    is_valid, resolved_path, error = validate_ssh_key_path(str(expanded_path))
    if not is_valid:
        print_error(f"Invalid SSH key path: {error}")
        return True

    # Store in CONFIG variable
    handler.repl.credential_manager.set_variable(
        SSH_KEY_GLOBAL, resolved_path, VariableType.CONFIG
    )
    print_success(f"Global SSH key set to: {resolved_path}")

    # Check if key needs passphrase
    key_needs_passphrase = check_key_needs_passphrase(resolved_path, skip_validation=True)

    if key_needs_passphrase:
        console.print("[yellow]This key requires a passphrase.[/yellow]")
        try:
            response = input("Set passphrase now? (Y/n): ").strip().lower()
            if len(response) > 10:
                print_warning("Invalid input, skipping")
            elif response != "n":
                passphrase = getpass.getpass("SSH key passphrase (hidden): ")
                if passphrase and len(passphrase) <= MAX_PASSPHRASE_LENGTH:
                    handler.repl.credential_manager.set_variable(
                        SSH_PASSPHRASE_GLOBAL, passphrase, VariableType.SECRET
                    )
                    print_success("✅ Passphrase cached for this session")
                elif passphrase:
                    print_warning("Passphrase too long, skipping")
                else:
                    print_warning("Empty passphrase, skipping")
        except (KeyboardInterrupt, EOFError):
            print_warning("\nPassphrase setup skipped")
    else:
        console.print("[dim]Key does not require a passphrase.[/dim]")

    console.print("[dim]This key will be used for hosts without specific config.[/dim]")
    return True

def clear_global_key(handler) -> bool:
    """Clear global SSH key configuration."""
    if not handler.repl:
        print_warning("REPL context not available")
        return True

    handler.repl.credential_manager.delete_variable(SSH_KEY_GLOBAL)
    handler.repl.credential_manager.delete_variable(SSH_PASSPHRASE_GLOBAL)
    print_success("Global SSH key configuration cleared")
    return True
