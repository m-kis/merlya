"""
Variables and credentials command handlers.

Handles: /variables, /credentials
"""

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning


class VariablesCommandHandler:
    """Handles variables-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def handle(self, args: list) -> bool:
        """Manage user variables and credentials."""
        from athena_ai.security.credentials import VariableType

        if not args:
            self._show_help()
            return True

        cmd = args[0]

        try:
            if cmd == 'set':
                self._handle_set(args[1:], VariableType)
            elif cmd == 'set-host':
                self._handle_set_host(args[1:])
            elif cmd in ['set-secret', 'secret']:
                self._handle_set_secret(args[1:], VariableType)
            elif cmd == 'list':
                self._handle_list(VariableType)
            elif cmd in ['delete', 'del', 'remove']:
                self._handle_delete(args[1:])
            elif cmd == 'clear':
                self._handle_clear()
            elif cmd == 'clear-secrets':
                self._handle_clear_secrets()
            else:
                print_warning(f"Unknown subcommand: {cmd}")
                self._show_help()

        except Exception as e:
            print_error(f"Variable operation failed: {e}")

        return True

    def _handle_set(self, args: list, VariableType):
        """Set a config variable."""
        if len(args) >= 2:
            key = args[0]
            value = ' '.join(args[1:])
            self.repl.credentials.set_variable(key, value, VariableType.CONFIG)
            print_success(f"Variable '{key}' = '{value}' [config]")
            console.print(f"[dim]Use @{key} in your queries (persisted)[/dim]")
        else:
            print_error("Missing key or value")

    def _handle_set_host(self, args: list):
        """Set a host alias."""
        if len(args) >= 2:
            key = args[0]
            value = ' '.join(args[1:])
            self.repl.credentials.set_host(key, value)
            print_success(f"Host alias '{key}' = '{value}' [host]")
            console.print(f"[dim]Use @{key} as hostname (persisted)[/dim]")
        else:
            print_error("Missing key or value")

    def _handle_set_secret(self, args: list, VariableType):
        """Set a secret (secure input)."""
        if len(args) >= 1:
            key = args[0]
            if self.repl.credentials.set_variable_secure(key, VariableType.SECRET):
                print_success(f"Secret '{key}' set [secret]")
                console.print("[dim]Secret stored in memory only (not persisted)[/dim]")
            else:
                print_warning("Secret not saved")
        else:
            print_error("Missing key")

    def _handle_list(self, VariableType):
        """List all variables."""
        variables = self.repl.credentials.list_variables_typed()
        if not variables:
            print_warning("No variables defined")
            console.print("[dim]Use /variables set <key> <value> to define one[/dim]")
        else:
            table = Table(title="User Variables")
            table.add_column("Variable", style="cyan")
            table.add_column("Type", style="yellow")
            table.add_column("Value", style="green")
            table.add_column("Persisted", style="magenta")

            for key, (value, var_type) in sorted(variables.items()):
                # Mask secrets completely
                if var_type == VariableType.SECRET:
                    display_value = "********"
                elif len(value) > 30:
                    display_value = value[:15] + "..." + value[-10:]
                else:
                    display_value = value

                persisted = "Yes" if var_type != VariableType.SECRET else "No"
                table.add_row(f"@{key}", var_type.value, display_value, persisted)

            console.print(table)
            console.print("\n[dim]HOST/CONFIG variables are persisted across sessions. SECRETS are memory-only.[/dim]")

    def _handle_delete(self, args: list):
        """Delete a variable."""
        if len(args) >= 1:
            key = args[0]
            if self.repl.credentials.delete_variable(key):
                print_success(f"Variable '{key}' deleted")
            else:
                print_warning(f"Variable '{key}' not found")
        else:
            print_error("Missing key")

    def _handle_clear(self):
        """Clear all variables."""
        self.repl.credentials.clear_session_credentials()
        self.repl.credentials.clear_variables()
        print_success("All credentials and variables cleared")

    def _handle_clear_secrets(self):
        """Clear only secrets."""
        self.repl.credentials.clear_secrets()
        print_success("All secrets cleared (hosts and configs preserved)")

    def _show_help(self):
        """Show help for /variables command."""
        console.print("[yellow]Usage:[/yellow]")
        console.print("  /variables list                    - List all variables")
        console.print("  /variables set <key> <value>       - Set config variable (persisted)")
        console.print("  /variables set-host <key> <value>  - Set host alias (persisted)")
        console.print("  /variables set-secret <key>        - Set secret (secure input, NOT persisted)")
        console.print("  /variables delete <key>            - Delete a variable")
        console.print("  /variables clear                   - Clear all variables")
        console.print("  /variables clear-secrets           - Clear only secrets")
        console.print()
        console.print("[yellow]Variable Types:[/yellow]")
        console.print("  [cyan]host[/cyan]   - Host aliases (@proddb → db-prod-001) - persisted")
        console.print("  [cyan]config[/cyan] - General values (@env, @region) - persisted")
        console.print("  [cyan]secret[/cyan] - Passwords, tokens - memory only")
        console.print()
        console.print("[yellow]Example:[/yellow]")
        console.print("  /variables set-host proddb db-prod-001")
        console.print("  /variables set-secret dbpass")
        console.print("  check mysql on @proddb using @dbpass")
