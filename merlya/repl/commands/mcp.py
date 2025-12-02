"""
MCP command handler.
"""
from rich.table import Table

from merlya.repl.ui import console, print_error, print_success, print_warning


def handle_mcp_command(repl, args):
    """Handle /mcp command for MCP server management."""
    if not args:
        console.print("[yellow]Usage:[/yellow]")
        console.print("  /mcp list - List configured servers")
        console.print("  /mcp add - Add a new server (interactive)")
        console.print("  /mcp delete <name> - Remove a server")
        console.print("  /mcp show <name> - Show server details")
        console.print("  /mcp examples - Show example configurations")
        return True

    cmd = args[0]

    if cmd == 'list':
        servers = repl.mcp_manager.list_servers()
        if not servers:
            print_warning("No MCP servers configured")
            console.print("[dim]💡 Use /mcp add to configure a server[/dim]")
        else:
            table = Table(title="MCP Servers")
            table.add_column("Name", style="cyan")
            table.add_column("Command", style="green")
            table.add_column("Status", style="yellow")

            for name, config in servers.items():
                cmd_str = config.get('command', 'N/A')
                status = "[green]✅[/green]" if config.get('enabled', True) else "[red]❌[/red]"
                table.add_row(name, cmd_str[:50], status)
            console.print(table)

    elif cmd == 'add':
        console.print("\n[bold cyan]➕ Add MCP Server[/bold cyan]\n")
        try:
            name = input("Server name: ").strip()
            command = input("Command (e.g., npx, uvx): ").strip()
            args_str = input("Arguments (space-separated, or empty): ").strip()
            env_str = input("Environment variables (KEY=VALUE, comma-separated, or empty): ").strip()

            if name and command:
                server_args = args_str.split() if args_str else []
                # Parse environment variables
                env_vars = {}
                if env_str:
                    for pair in env_str.split(','):
                        pair = pair.strip()
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            env_vars[key.strip()] = value.strip()

                # Build config dict as expected by MCPManager
                config = {
                    "type": "stdio",
                    "command": command,
                    "args": server_args,
                }
                if env_vars:
                    config["env"] = env_vars

                repl.mcp_manager.add_server(name, config)
                print_success(f"MCP server '{name}' added")
            else:
                print_error("Name and command are required")
        except (KeyboardInterrupt, EOFError):
            print_warning("Cancelled")

    elif cmd == 'delete' and len(args) > 1:
        name = args[1]
        if repl.mcp_manager.remove_server(name):
            print_success(f"Server '{name}' removed")
        else:
            print_error(f"Server '{name}' not found")

    elif cmd == 'show' and len(args) > 1:
        name = args[1]
        servers = repl.mcp_manager.list_servers()
        if name in servers:
            config = servers[name]
            console.print(f"\n[bold]{name}[/bold]")
            console.print(f"  Command: {config.get('command')}")
            console.print(f"  Args: {config.get('args', [])}")
            console.print(f"  Env: {config.get('env', {})}")
        else:
            print_error(f"Server '{name}' not found")

    elif cmd == 'examples':
        console.print("\n[bold]Example MCP Servers:[/bold]\n")
        console.print("  [cyan]Filesystem:[/cyan]")
        console.print("    npx @modelcontextprotocol/server-filesystem /path/to/dir\n")
        console.print("  [cyan]Git:[/cyan]")
        console.print("    npx @modelcontextprotocol/server-git --repository /path/to/repo\n")
        console.print("  [cyan]PostgreSQL:[/cyan]")
        console.print("    npx @modelcontextprotocol/server-postgres postgresql://...\n")

    return True
