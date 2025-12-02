"""
SSH passphrase command handler.
"""
import getpass
from pathlib import Path
from typing import List, Optional

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.credentials import VariableType
from merlya.security.ssh_credentials import validate_passphrase_for_key

SSH_PASSPHRASE_GLOBAL = "ssh-passphrase-global"
SSH_PASSPHRASE_PREFIX = "ssh-passphrase-"
SSH_KEY_GLOBAL = "ssh_key_global"
MAX_INPUT_LENGTH = 256
MAX_PASSPHRASE_LENGTH = 1024


def _resolve_key_path(handler, key_ref: str) -> Optional[str]:
    """
    Resolve a key reference to an actual file path.

    Args:
        handler: SSH command handler
        key_ref: Key reference (name like 'id_ed25519', path, or 'global')

    Returns:
        Resolved path or None if not found
    """
    if key_ref.lower() == "global":
        # Get global key path
        return handler.repl.credential_manager.get_variable(SSH_KEY_GLOBAL)

    # Check if it's a full path
    if "/" in key_ref or key_ref.startswith("~"):
        path = Path(key_ref).expanduser().resolve()
        if path.exists():
            return str(path)
        return None

    # Just key name - look in ~/.ssh
    ssh_dir = Path.home() / ".ssh"
    key_path = ssh_dir / key_ref
    if key_path.exists():
        return str(key_path)

    return None


def handle_passphrase(handler, args: List[str]) -> bool:
    """Handle passphrase management with validation."""
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

    # Determine secret key name and display name
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

    # Resolve actual key path for validation
    key_path = _resolve_key_path(handler, key_ref)
    can_validate = key_path is not None

    if not can_validate:
        console.print(f"[yellow]⚠️ Key file not found for '{display_name}'[/yellow]")
        console.print("[dim]Passphrase will be stored without validation[/dim]")

    # Check if already cached
    existing = handler.repl.credential_manager.get_variable(secret_key)
    if existing:
        console.print(f"Passphrase for [cyan]{display_name}[/cyan] is already cached.")
        response = input("Update it? (y/N): ").strip().lower()
        if len(response) > 10 or response != "y":
            return True

    try:
        max_attempts = 3 if can_validate else 1

        for attempt in range(max_attempts):
            passphrase = getpass.getpass(f"Enter passphrase for {display_name} (hidden): ")

            if not passphrase:
                print_warning("Empty passphrase, not saved")
                return True

            if len(passphrase) > MAX_PASSPHRASE_LENGTH:
                print_warning("Passphrase too long")
                if can_validate and attempt < max_attempts - 1:
                    console.print("[dim]Try again[/dim]")
                    continue
                return True

            # Validate passphrase if we have the key path
            if can_validate:
                is_valid, error = validate_passphrase_for_key(key_path, passphrase)
                if is_valid:
                    handler.repl.credential_manager.set_variable(
                        secret_key, passphrase, VariableType.SECRET
                    )
                    print_success(f"✅ Passphrase verified and cached (stored as @{secret_key})")
                    return True
                else:
                    remaining = max_attempts - attempt - 1
                    if remaining > 0:
                        print_error(f"❌ {error}. {remaining} attempt(s) remaining.")
                    else:
                        print_error(f"❌ {error}. No attempts remaining.")
            else:
                # No validation possible, just store it
                handler.repl.credential_manager.set_variable(
                    secret_key, passphrase, VariableType.SECRET
                )
                print_success(f"✅ Passphrase cached (stored as @{secret_key})")
                console.print("[yellow]⚠️ Could not validate - ensure it's correct[/yellow]")
                return True

    except (KeyboardInterrupt, EOFError):
        print_warning("\nCancelled")

    return True
