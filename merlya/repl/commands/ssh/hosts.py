"""
SSH hosts command handler.
"""
import getpass
from pathlib import Path
from typing import List

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.credentials import VariableType
from merlya.security.ssh_credentials import validate_ssh_key_path

SSH_PASSPHRASE_PREFIX = "ssh-passphrase-"
MAX_INPUT_LENGTH = 256
MAX_PASSPHRASE_LENGTH = 1024

def handle_host(handler, args: List[str]) -> bool:
    """Handle /ssh host <hostname> subcommands."""
    if not args:
        print_error("Usage: /ssh host <hostname> [show|set|clear]")
        return True

    hostname = args[0]
    subcmd = args[1].lower() if len(args) > 1 else "show"

    if subcmd == "show":
        return show_host_config(handler, hostname)
    elif subcmd == "set":
        return set_host_key(handler, hostname)
    elif subcmd == "clear":
        return clear_host_config(handler, hostname)
    else:
        print_error(f"Unknown subcommand: {subcmd}")
        console.print("[dim]Use: show, set, or clear[/dim]")
        return True

def show_host_config(handler, hostname: str) -> bool:
    """Show SSH configuration for a specific host."""
    console.print(f"\n[bold]🔑 SSH Configuration for {hostname}[/bold]\n")

    if not handler.repo:
        print_warning("Inventory not available")
        return True

    host = handler.repo.get_host_by_name(hostname)
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
        if handler.repl and handler.repl.credential_manager.get_variable(ssh_passphrase_secret):
            console.print(f"  Passphrase: [green]Cached as @{ssh_passphrase_secret}[/green]")
        else:
            console.print(f"  Passphrase: [yellow]Configured but not cached (@{ssh_passphrase_secret})[/yellow]")
    else:
        console.print("  Passphrase: [dim]Not configured[/dim]")

    # Show what would actually be used
    if handler.repl:
        key_path, passphrase, source = handler.repl.credentials.resolve_ssh_for_host(
            hostname, prompt_passphrase=False
        )
        if key_path:
            console.print(f"\n  [dim]Effective key: {key_path} (from {source})[/dim]")

    console.print()
    return True

def set_host_key(handler, hostname: str) -> bool:
    """Set SSH key for a specific host."""
    if not handler.repo:
        print_warning("Inventory not available")
        return True

    host = handler.repo.get_host_by_name(hostname)
    if not host:
        print_warning(f"Host '{hostname}' not found in inventory")
        console.print("[dim]Add it first with: /inventory add-host[/dim]")
        return True

    if not handler.repl:
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

        # Input validation
        if len(ssh_key_path) > MAX_INPUT_LENGTH:
            print_error("Path too long")
            return True

        # Expand path
        expanded_path = Path(ssh_key_path).expanduser()

        # Validate path security first
        is_valid, resolved_path, error = validate_ssh_key_path(str(expanded_path))
        if not is_valid:
            print_error(f"Invalid SSH key path: {error}")
            return True

        if not expanded_path.exists():
            print_warning(f"SSH key not found at: {expanded_path}")
            response = input("Continue anyway? (y/N): ").strip().lower()
            if len(response) > 10 or response != "y":
                return True

        # Update metadata with validated path
        metadata["ssh_key_path"] = resolved_path or str(expanded_path)

        # Ask about passphrase
        passphrase_response = input("Set/update passphrase? (y/N): ").strip().lower()
        if len(passphrase_response) <= 10 and passphrase_response == "y":
            secret_key = f"{SSH_PASSPHRASE_PREFIX}{hostname}"
            passphrase = getpass.getpass("SSH key passphrase (hidden): ")

            if passphrase and len(passphrase) <= MAX_PASSPHRASE_LENGTH:
                handler.repl.credential_manager.set_variable(
                    secret_key, passphrase, VariableType.SECRET
                )
                metadata["ssh_passphrase_secret"] = secret_key
                print_success(f"Passphrase stored as secret: @{secret_key}")
            elif passphrase:
                print_warning("Passphrase too long, skipping")

        # Update host in inventory
        handler.repo.add_host(
            hostname=hostname,
            metadata=metadata,
            changed_by="user",
        )
        print_success(f"SSH key configured for {hostname}")

    except (KeyboardInterrupt, EOFError):
        print_warning("\nCancelled")

    return True

def clear_host_config(handler, hostname: str) -> bool:
    """Clear SSH configuration for a specific host."""
    if not handler.repo:
        print_warning("Inventory not available")
        return True

    host = handler.repo.get_host_by_name(hostname)
    if not host:
        print_warning(f"Host '{hostname}' not found in inventory")
        return True

    metadata = host.get("metadata", {}) or {}

    # Clear SSH config
    if "ssh_key_path" in metadata:
        del metadata["ssh_key_path"]

    # Also clear passphrase secret if exists
    secret_key = metadata.pop("ssh_passphrase_secret", None)
    if secret_key and handler.repl:
        handler.repl.credential_manager.delete_variable(secret_key)
        console.print(f"  [dim]Cleared secret: @{secret_key}[/dim]")

    handler.repo.add_host(
        hostname=hostname,
        metadata=metadata,
        changed_by="user",
    )
    print_success(f"SSH configuration cleared for {hostname}")
    return True
