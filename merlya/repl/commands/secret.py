"""
Secret management command handler.

Handles: /secret

Provides secure storage for secrets with both session (in-memory) and
persistent (keyring) storage options.
"""
import getpass
import logging
from typing import List

from rich.table import Table

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.keyring_store import get_keyring_store

logger = logging.getLogger(__name__)


class SecretCommandHandler:
    """
    Handles secret-related slash commands.

    Commands:
    - /secret set <key> [--persist|-p]  : Set a secret (session or keyring)
    - /secret list [--persistent|--session] : List secrets
    - /secret delete <key> [--all]      : Delete a secret
    - /secret clear --session           : Clear session secrets
    - /secret persist <key>|--all       : Move secret to keyring
    - /secret info                      : Show keyring info
    """

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl
        self._keyring = get_keyring_store()

    def handle(self, args: List[str]) -> bool:
        """Handle /secret command and subcommands."""
        if not args:
            self._show_help()
            return True

        cmd = args[0].lower()

        try:
            if cmd == "set":
                return self._handle_set(args[1:])
            elif cmd == "list":
                return self._handle_list(args[1:])
            elif cmd in ["delete", "del", "remove", "rm"]:
                return self._handle_delete(args[1:])
            elif cmd == "clear":
                return self._handle_clear(args[1:])
            elif cmd == "persist":
                return self._handle_persist(args[1:])
            elif cmd == "info":
                return self._handle_info()
            elif cmd == "export":
                return self._handle_export(args[1:])
            elif cmd == "import":
                return self._handle_import(args[1:])
            else:
                print_warning(f"Unknown subcommand: {cmd}")
                self._show_help()
                return False

        except Exception as e:
            logger.exception("Secret operation failed: %s", e)
            print_error(f"Secret operation failed: {e}")
            return False

    def _handle_set(self, args: List[str]) -> bool:
        """
        Set a secret.

        Usage:
            /secret set <key>           - Session only (default)
            /secret set <key> --persist - Store in keyring
            /secret set <key> -p        - Store in keyring (short)
        """
        if not args:
            print_error("Usage: /secret set <key> [--persist|-p]")
            return False

        key = args[0]
        persist = "--persist" in args or "-p" in args

        # Prompt for secret value securely
        try:
            console.print(f"\n[cyan]Enter secret value for '{key}':[/cyan]")
            value = getpass.getpass("Secret: ")

            if not value:
                print_warning("Empty value - not saved")
                return False

            # Store based on persistence flag
            if persist:
                if not self._keyring.is_available:
                    print_error("Keyring not available. Secret stored in session only.")
                    self._store_session_secret(key, value)
                else:
                    if self._keyring.store(key, value):
                        print_success(f"Secret '{key}' stored in system keyring (persistent)")
                        # Also cache in session for immediate use
                        self._store_session_secret(key, value, silent=True)
                    else:
                        print_error("Failed to store in keyring")
                        return False
            else:
                self._store_session_secret(key, value)
                print_success(f"Secret '{key}' stored in session (expires on exit)")
                console.print("[dim]Use --persist to store in system keyring[/dim]")

            return True

        except ValueError as e:
            # Key validation error
            print_error(f"Invalid key: {e}")
            return False
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled[/yellow]")
            return False

    def _store_session_secret(self, key: str, value: str, silent: bool = False) -> None:
        """Store secret in session (in-memory)."""
        from merlya.security.credentials import VariableType

        self.repl.credentials.set_variable(key, value, VariableType.SECRET)
        if not silent:
            logger.debug(f"🔒 Secret stored in session: {key}")

    def _handle_list(self, args: List[str]) -> bool:
        """
        List secrets.

        Usage:
            /secret list              - List all secrets
            /secret list --persistent - List keyring secrets only
            /secret list --session    - List session secrets only
        """
        from merlya.security.credentials import VariableType

        show_persistent = "--persistent" in args or "-p" in args
        show_session = "--session" in args or "-s" in args

        # Default: show both
        if not show_persistent and not show_session:
            show_persistent = True
            show_session = True

        table = Table(title="🔐 Secrets")
        table.add_column("Name", style="cyan")
        table.add_column("Storage", style="yellow")
        table.add_column("Value", style="green")

        secrets_found = False

        # List session secrets
        if show_session:
            session_secrets = self.repl.credentials.list_variables_by_type(
                VariableType.SECRET
            )
            for key in sorted(session_secrets.keys()):
                table.add_row(f"@{key}", "session", "********")
                secrets_found = True

        # List keyring secrets
        if show_persistent and self._keyring.is_available:
            keyring_keys = self._keyring.list_keys()
            # Filter out credential keys (cred/...)
            user_keys = [k for k in keyring_keys if not k.startswith("cred/")]
            for key in sorted(user_keys):
                # Check if already shown as session secret
                if not show_session or key not in self.repl.credentials.list_variables_by_type(
                    VariableType.SECRET
                ):
                    table.add_row(f"@{key}", "keyring", "********")
                    secrets_found = True

        if secrets_found:
            console.print(table)
            console.print()
            if show_session:
                console.print(
                    "[dim]Session secrets expire on exit. "
                    "Use '/secret persist <key>' to save to keyring.[/dim]"
                )
        else:
            print_warning("No secrets found")
            console.print("[dim]Use '/secret set <key>' to create one[/dim]")

        return True

    def _handle_delete(self, args: List[str]) -> bool:
        """
        Delete a secret.

        Usage:
            /secret delete <key>       - Delete from session
            /secret delete <key> --all - Delete from both session and keyring
        """
        from merlya.security.credentials import VariableType

        if not args:
            print_error("Usage: /secret delete <key> [--all]")
            return False

        key = args[0]
        delete_all = "--all" in args or "-a" in args

        deleted_session = False
        deleted_keyring = False

        # Delete from session
        if self.repl.credentials.get_variable_type(key) == VariableType.SECRET:
            self.repl.credentials.delete_variable(key)
            deleted_session = True

        # Delete from keyring
        if delete_all or not deleted_session:
            if self._keyring.is_available and self._keyring.delete(key):
                deleted_keyring = True

        if deleted_session and deleted_keyring:
            print_success(f"✅ Secret '{key}' deleted from session and keyring")
        elif deleted_session:
            print_success(f"✅ Secret '{key}' deleted from session")
        elif deleted_keyring:
            print_success(f"✅ Secret '{key}' deleted from keyring")
        else:
            print_warning(f"Secret '{key}' not found")

        return True

    def _handle_clear(self, args: List[str]) -> bool:
        """
        Clear secrets.

        Usage:
            /secret clear --session   - Clear session secrets only
            /secret clear --keyring   - Clear keyring secrets (with confirmation)
            /secret clear --all       - Clear both (with confirmation)
        """
        clear_session = "--session" in args or "-s" in args
        clear_keyring = "--keyring" in args or "-k" in args
        clear_all = "--all" in args or "-a" in args

        if not clear_session and not clear_keyring and not clear_all:
            print_error("Usage: /secret clear [--session|--keyring|--all]")
            console.print("[dim]Specify what to clear:[/dim]")
            console.print("  --session (-s): Session secrets only")
            console.print("  --keyring (-k): Keyring secrets (requires confirmation)")
            console.print("  --all (-a): Both session and keyring")
            return False

        if clear_all:
            clear_session = True
            clear_keyring = True

        # Clear session
        if clear_session:
            self.repl.credentials.clear_secrets()
            print_success("✅ Session secrets cleared")

        # Clear keyring (with confirmation)
        if clear_keyring:
            if not self._keyring.is_available:
                print_warning("Keyring not available")
            else:
                keys = self._keyring.list_keys()
                user_keys = [k for k in keys if not k.startswith("cred/")]

                if not user_keys:
                    print_warning("No keyring secrets to clear")
                else:
                    console.print(
                        f"\n[yellow]⚠️ This will permanently delete {len(user_keys)} "
                        f"secret(s) from the system keyring.[/yellow]"
                    )
                    confirm = input("Type 'yes' to confirm: ")

                    if confirm.lower() == "yes":
                        for key in user_keys:
                            self._keyring.delete(key)
                        print_success(f"✅ Deleted {len(user_keys)} keyring secret(s)")
                    else:
                        print_warning("Cancelled")

        return True

    def _handle_persist(self, args: List[str]) -> bool:
        """
        Persist session secret to keyring.

        Usage:
            /secret persist <key>  - Move specific secret to keyring
            /secret persist --all  - Move all session secrets to keyring
        """
        from merlya.security.credentials import VariableType

        if not self._keyring.is_available:
            print_error("❌ Keyring not available on this system")
            return False

        persist_all = "--all" in args or "-a" in args

        if persist_all:
            # Persist all session secrets
            secrets = self.repl.credentials.list_variables_by_type(VariableType.SECRET)
            if not secrets:
                print_warning("No session secrets to persist")
                return False

            persisted = 0
            for key, value in secrets.items():
                if self._keyring.store(key, value):
                    persisted += 1

            print_success(f"✅ Persisted {persisted}/{len(secrets)} secret(s) to keyring")
            return True

        # Persist specific key
        if not args or args[0].startswith("-"):
            print_error("Usage: /secret persist <key> | --all")
            return False

        key = args[0]
        value = self.repl.credentials.get_variable(key)

        if value is None:
            print_warning(f"Secret '{key}' not found in session")
            return False

        # Check type
        var_type = self.repl.credentials.get_variable_type(key)
        if var_type != VariableType.SECRET:
            print_warning(f"'{key}' is not a secret (type: {var_type.value})")
            return False

        if self._keyring.store(key, value):
            print_success(f"✅ Secret '{key}' persisted to system keyring")
            return True
        else:
            print_error(f"Failed to persist '{key}' to keyring")
            return False

    def _handle_info(self) -> bool:
        """Show keyring information."""
        console.print("\n[bold]🔐 Secret Storage Info[/bold]\n")

        # Session info
        from merlya.security.credentials import VariableType

        session_count = len(
            self.repl.credentials.list_variables_by_type(VariableType.SECRET)
        )
        console.print(f"[cyan]Session secrets:[/cyan] {session_count}")
        console.print("[dim]  In-memory only, expire on exit[/dim]")

        # Keyring info
        console.print()
        if self._keyring.is_available:
            console.print(f"[cyan]Keyring backend:[/cyan] {self._keyring.backend_name}")
            keyring_keys = self._keyring.list_keys()
            user_keys = [k for k in keyring_keys if not k.startswith("cred/")]
            cred_count = len([k for k in keyring_keys if k.startswith("cred/")])
            console.print(f"[cyan]Keyring secrets:[/cyan] {len(user_keys)}")
            console.print(f"[cyan]Stored credentials:[/cyan] {cred_count}")
            console.print("[dim]  Persistent, OS-encrypted[/dim]")
        else:
            console.print("[yellow]Keyring:[/yellow] Not available")
            console.print("[dim]  Install 'keyring' package for persistent storage[/dim]")

        # Environment fallback
        console.print()
        console.print("[cyan]Environment fallback:[/cyan] MERLYA_<KEY>")
        console.print("[dim]  Checked last when resolving secrets[/dim]")

        return True

    def _handle_export(self, args: List[str]) -> bool:
        """
        Export secret keys (not values) for backup.

        Usage:
            /secret export <filename>
        """
        if not args:
            print_error("Usage: /secret export <filename>")
            return False

        filename = args[0]

        keys = []

        # Collect session secrets
        from merlya.security.credentials import VariableType

        session_keys = list(
            self.repl.credentials.list_variables_by_type(VariableType.SECRET).keys()
        )
        keys.extend(session_keys)

        # Collect keyring secrets
        if self._keyring.is_available:
            keyring_keys = [
                k for k in self._keyring.list_keys() if not k.startswith("cred/")
            ]
            for k in keyring_keys:
                if k not in keys:
                    keys.append(k)

        if not keys:
            print_warning("No secrets to export")
            return False

        try:
            with open(filename, "w") as f:
                f.write("# Merlya secret keys export\n")
                f.write("# Use '/secret import <file>' to restore\n")
                for key in sorted(keys):
                    f.write(f"{key}\n")

            print_success(f"✅ Exported {len(keys)} secret key(s) to {filename}")
            console.print("[dim]Note: Values are NOT exported (security)[/dim]")
            return True

        except Exception as e:
            print_error(f"Export failed: {e}")
            return False

    def _handle_import(self, args: List[str]) -> bool:
        """
        Import secret keys and prompt for values.

        Usage:
            /secret import <filename> [--persist|-p]
        """
        if not args:
            print_error("Usage: /secret import <filename> [--persist|-p]")
            return False

        filename = args[0]
        persist = "--persist" in args or "-p" in args

        try:
            with open(filename, "r") as f:
                lines = f.readlines()

            keys = [
                line.strip()
                for line in lines
                if line.strip() and not line.startswith("#")
            ]

            if not keys:
                print_warning("No keys found in file")
                return False

            console.print(f"\n[cyan]Importing {len(keys)} secret(s)...[/cyan]")
            console.print("[dim]Enter value for each, or press Enter to skip[/dim]\n")

            imported = 0
            for key in keys:
                try:
                    value = getpass.getpass(f"{key}: ")
                    if value:
                        if persist and self._keyring.is_available:
                            self._keyring.store(key, value)
                        else:
                            self._store_session_secret(key, value, silent=True)
                        imported += 1
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Import cancelled[/yellow]")
                    break

            storage = "keyring" if persist else "session"
            print_success(f"✅ Imported {imported}/{len(keys)} secret(s) to {storage}")
            return True

        except FileNotFoundError:
            print_error(f"File not found: {filename}")
            return False
        except Exception as e:
            print_error(f"Import failed: {e}")
            return False

    def _show_help(self) -> None:
        """Show help for /secret command."""
        console.print("[bold]🔐 Secret Management[/bold]\n")
        console.print("[yellow]Commands:[/yellow]")
        console.print("  /secret set <key> [--persist|-p]   Set a secret")
        console.print("  /secret list [--persistent|--session]  List secrets")
        console.print("  /secret delete <key> [--all]       Delete a secret")
        console.print("  /secret clear [--session|--keyring|--all]  Clear secrets")
        console.print("  /secret persist <key>|--all        Move to keyring")
        console.print("  /secret info                       Show storage info")
        console.print("  /secret export <file>              Export keys (not values)")
        console.print("  /secret import <file> [--persist]  Import and prompt values")
        console.print()
        console.print("[yellow]Storage:[/yellow]")
        console.print("  [cyan]session[/cyan]  - In-memory, expires on exit (default)")
        console.print("  [cyan]keyring[/cyan]  - Persistent, OS-encrypted (--persist)")
        console.print()
        console.print("[yellow]Examples:[/yellow]")
        console.print("  /secret set db-password")
        console.print("  /secret set api-key --persist")
        console.print("  /secret list --persistent")
        console.print("  /secret persist db-password")
