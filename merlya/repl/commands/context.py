"""
Context-related command handlers.

Handles: /scan, /refresh, /cache-stats, /context, /ssh-info, /permissions
"""

from rich.table import Table

from merlya.repl.ui import console, print_error, print_success, print_warning


class ContextCommandHandler:
    """Handles context-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    async def handle_scan(self, args: list) -> bool:
        """
        Scan local machine or a specific remote host.

        Usage:
            /scan           - Scan local machine only
            /scan <host>    - Scan a specific remote host
        """
        try:
            if args:
                hostname = args[0]
                await self._scan_host(hostname)
            else:
                self._scan_local()
        except Exception as e:
            print_error(f"Scan failed: {e}")

        return True

    def _scan_local(self):
        """Scan local machine only."""
        with console.status("[cyan]Scanning local machine...[/cyan]", spinner="dots"):
            context = self.repl.context_manager.discover_environment()

        local = context.get('local', {})
        os_info = local.get('os_info', {})

        print_success("Local scan complete")
        console.print(f"  Hostname: {os_info.get('hostname', 'unknown')}")
        console.print(f"  OS: {os_info.get('os', 'unknown')} {os_info.get('release', '')}")

        inventory = context.get('inventory', {})
        console.print(f"  Inventory: {len(inventory)} hosts")

    async def _scan_host(self, hostname: str):
        """Scan a specific remote host."""
        with console.status(f"[cyan]Scanning {hostname}...[/cyan]", spinner="dots"):
            result = await self.repl.context_manager.scan_host(hostname, force=True)

        if result.get('accessible'):
            print_success(f"Host {hostname} scanned successfully")
            console.print(f"  IP: {result.get('ip', 'unknown')}")
            console.print("  Reachable: Yes")
            if result.get('os'):
                console.print(f"  OS: {result.get('os', 'unknown')}")
        else:
            print_warning(f"Host {hostname} not accessible")
            if result.get('error'):
                console.print(f"  Error: {result.get('error')}")

    async def handle_refresh(self, args: list) -> bool:
        """
        Force refresh context cache.

        Usage:
            /refresh           - Refresh local context cache
            /refresh <host>    - Refresh cache for a specific host
        """
        try:
            if args:
                hostname = args[0]
                await self._refresh_host(hostname)
            else:
                self._refresh_local()
        except Exception as e:
            print_error(f"Refresh failed: {e}")

        return True

    def _refresh_local(self):
        """Refresh local context cache."""
        with console.status("[cyan]Refreshing local context...[/cyan]", spinner="dots"):
            self.repl.context_manager.discover_environment(force=True)
        print_success("Local context refreshed (cache cleared)")

    async def _refresh_host(self, hostname: str):
        """Refresh cache for a specific host."""
        with console.status(f"[cyan]Refreshing {hostname}...[/cyan]", spinner="dots"):
            result = await self.repl.context_manager.scan_host(hostname, force=True)

        if result.get('accessible'):
            print_success(f"Cache refreshed for {hostname}")
        else:
            print_warning(f"Host {hostname} not accessible")
            if result.get('error'):
                console.print(f"  Error: {result.get('error')}")

    def handle_cache_stats(self) -> bool:
        """Show cache statistics."""
        try:
            stats = self.repl.context_manager.get_cache_stats()

            if not stats:
                print_warning("No cache data available yet")
                return True

            table = Table(title="Cache Statistics")
            table.add_column("Component", style="cyan")
            table.add_column("Age", style="yellow")
            table.add_column("TTL", style="blue")
            table.add_column("Status", style="green")
            table.add_column("Fingerprint", style="magenta")

            for key, info in stats.items():
                status = "Valid" if info['valid'] else "Expired"
                status_style = "green" if info['valid'] else "red"
                fingerprint = "Yes" if info.get('has_fingerprint') else "No"

                table.add_row(
                    key,
                    f"{info['age_seconds']}s",
                    f"{info['ttl_seconds']}s",
                    f"[{status_style}]{status}[/{status_style}]",
                    fingerprint
                )

            console.print(table)
            console.print("\n[dim]Valid = Cache is fresh, Expired = Will auto-refresh on next access[/dim]")

        except Exception as e:
            print_error(f"Failed to get cache stats: {e}")

        return True

    def handle_context(self) -> bool:
        """Show current infrastructure context."""
        try:
            context = self.repl.context_manager.get_context()
            local = context.get('local', {})
            os_info = local.get('os_info', {})
            inventory = context.get('inventory', {})

            console.print("\n[bold]Current Context[/bold]")
            console.print(f"  Local: {os_info.get('hostname', 'unknown')} ({os_info.get('os', 'unknown')})")
            console.print(f"  Inventory: {len(inventory)} hosts\n")

        except Exception as e:
            print_error(f"Failed to get context: {e}")

        return True

    def handle_ssh_info(self) -> bool:
        """Show SSH configuration and available keys."""
        try:
            console.print("\n[bold]SSH Configuration[/bold]\n")

            if self.repl.credentials.supports_agent():
                agent_keys = self.repl.credentials.get_agent_keys()
                if agent_keys:
                    console.print(f"[green]ssh-agent: {len(agent_keys)} keys loaded[/green]")
                else:
                    print_warning("ssh-agent detected but no keys")
            else:
                print_warning("ssh-agent not available")

            keys = self.repl.credentials.get_ssh_keys()
            console.print(f"\nSSH Keys: {len(keys)} available")

            default_key = self.repl.credentials.get_default_key()
            if default_key:
                console.print(f"Default: {default_key}\n")

        except Exception as e:
            print_error(f"Failed to get SSH info: {e}")

        return True

    def handle_permissions(self, args: list) -> bool:
        """Show permission capabilities."""
        if not args:
            # Show cached permission info for all hosts
            if not self.repl.orchestrator.permissions.capabilities_cache:
                print_warning("No permission data cached yet.")
                console.print("[dim]Run commands on hosts to detect permissions automatically.[/dim]")
            else:
                console.print("\n[bold]Permission Capabilities (Cached)[/bold]\n")
                for target in self.repl.orchestrator.permissions.capabilities_cache:
                    console.print(f"[cyan]{target}[/cyan]:")
                    console.print(self.repl.orchestrator.permissions.format_capabilities_summary(target))
                    console.print()
        else:
            # Show permissions for specific host
            target = args[0]
            console.print(f"\n[bold]Detecting permissions on {target}...[/bold]\n")
            try:
                self.repl.orchestrator.permissions.detect_capabilities(target)
                console.print(self.repl.orchestrator.permissions.format_capabilities_summary(target))
            except Exception as e:
                print_error(f"Permission detection failed: {e}")
        return True
