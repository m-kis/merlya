"""
SSH agent command handler.
"""
from rich.table import Table
from merlya.repl.ui import console, print_warning

def show_agent(handler) -> bool:
    """Show detailed ssh-agent information."""
    console.print("\n[bold]🔐 SSH Agent Status[/bold]\n")

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    credentials = handler.repl.credentials

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
