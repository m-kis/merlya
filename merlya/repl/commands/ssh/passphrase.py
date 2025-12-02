"""
SSH passphrase command handler.
"""
import getpass
from pathlib import Path
from typing import List

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.credentials import VariableType

SSH_PASSPHRASE_GLOBAL = "ssh-passphrase-global"
SSH_PASSPHRASE_PREFIX = "ssh-passphrase-"
MAX_INPUT_LENGTH = 256
MAX_PASSPHRASE_LENGTH = 1024

def handle_passphrase(handler, args: List[str]) -> bool:
    """Handle passphrase management."""
    if not args:
        print_error("Usage: /ssh passphrase <key_name_or_path>")
        console.print("[dim]Example: /ssh passphrase id_ed25519[/dim]")
        console.print("[dim]Example: /ssh passphrase global[/dim]")
        return True

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    key_ref = args[0]

    # Input validation
    if len(key_ref) > MAX_INPUT_LENGTH:
        print_error("Key reference too long")
        return True

    # Determine secret key name
    if key_ref.lower() == "global":
        secret_key = SSH_PASSPHRASE_GLOBAL
        display_name = "global key"
    elif "/" in key_ref or key_ref.startswith("~"):
        # Full path provided
        key_name = Path(key_ref).name
        secret_key = f"{SSH_PASSPHRASE_PREFIX}{key_name}"
        display_name = key_name
    else:
        # Just key name (e.g., id_ed25519)
        secret_key = f"{SSH_PASSPHRASE_PREFIX}{key_ref}"
        display_name = key_ref

    # Check if already cached
    existing = handler.repl.credential_manager.get_variable(secret_key)
    if existing:
        console.print(f"Passphrase for [cyan]{display_name}[/cyan] is already cached.")
        response = input("Update it? (y/N): ").strip().lower()
        if len(response) > 10 or response != "y":
            return True

    try:
        passphrase = getpass.getpass(f"Enter passphrase for {display_name} (hidden): ")
        if passphrase and len(passphrase) <= MAX_PASSPHRASE_LENGTH:
            handler.repl.credential_manager.set_variable(
                secret_key, passphrase, VariableType.SECRET
            )
            print_success(f"✅ Passphrase cached for session (stored as @{secret_key})")
        elif passphrase:
            print_warning("Passphrase too long, not saved")
        else:
            print_warning("Empty passphrase, not saved")
    except (KeyboardInterrupt, EOFError):
        print_warning("\nCancelled")

    return True
