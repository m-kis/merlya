"""
SSH test command handler.
"""
from typing import List

from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.security.ssh_credentials import sanitize_path_for_log


def handle_test(handler, args: List[str]) -> bool:
    """Test SSH connection to a host."""
    if not args:
        print_error("Usage: /ssh test <hostname>")
        return True

    hostname = args[0]
    console.print(f"\n[bold]🔌 Testing SSH connection to {hostname}[/bold]\n")

    if not handler.repl:
        print_warning("REPL context not available")
        return True

    # Resolve credentials
    credentials = handler.repl.credentials
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
