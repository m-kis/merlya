"""
Context-related command handlers.

Handles: /scan, /refresh, /cache-stats, /context
"""

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning


class ContextCommandHandler:
    """Handles context-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def handle_scan(self, args: list) -> bool:
        """Scan infrastructure. Use --full to scan remote hosts via SSH."""
        full = '--full' in args

        try:
            if full:
                self._scan_full()
            else:
                self._scan_quick()

        except Exception as e:
            print_error(f"Scan failed: {e}")

        return True

    def _scan_full(self):
        """Full SSH scan with progress bar."""
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TaskProgressColumn,
            TextColumn,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}[/cyan]"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[host]}[/dim]"),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning hosts...", total=None, host="")

            def update_progress(current, total, hostname):
                progress.update(task, total=total, completed=current, host=hostname)

            context = self.repl.context_manager.discover_environment(
                scan_remote=True,
                progress_callback=update_progress
            )
            # Mark complete
            progress.update(task, completed=task.total or 0, host="done")

        self._display_scan_results(context, is_full=True)

    def _scan_quick(self):
        """Quick scan without SSH."""
        with console.status("[cyan]Scanning infrastructure...[/cyan]", spinner="dots"):
            context = self.repl.context_manager.discover_environment(scan_remote=False)

        self._display_scan_results(context, is_full=False)

    def _display_scan_results(self, context: dict, is_full: bool):
        """Display scan results."""
        local = context.get('local', {})
        inventory = context.get('inventory', {})
        remote_hosts = context.get('remote_hosts', {})

        print_success("Scan complete")
        console.print(f"  Local: {local.get('hostname')}")
        console.print(f"  Inventory: {len(inventory)} hosts")

        if remote_hosts:
            accessible = sum(1 for h in remote_hosts.values() if h.get('accessible'))
            console.print(f"  Remote: {accessible}/{len(remote_hosts)} accessible")

    def handle_refresh(self, args: list) -> bool:
        """Force refresh context. Use --full to include SSH scan of remote hosts."""
        full = '--full' in args

        try:
            if full:
                self._refresh_full()
            else:
                self._refresh_quick()

        except Exception as e:
            print_error(f"Refresh failed: {e}")

        return True

    def _refresh_full(self):
        """Full refresh with SSH scan."""
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TaskProgressColumn,
            TextColumn,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}[/cyan]"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[host]}[/dim]"),
            console=console,
        ) as progress:
            task = progress.add_task("Refreshing (full)...", total=None, host="")

            def update_progress(current, total, hostname):
                progress.update(task, total=total, completed=current, host=hostname)

            context = self.repl.context_manager.discover_environment(
                scan_remote=True,
                force=True,
                progress_callback=update_progress
            )
            progress.update(task, completed=task.total or 0, host="done")

        remote_hosts = context.get('remote_hosts', {})
        accessible = sum(1 for h in remote_hosts.values() if h.get('accessible'))
        print_success(f"Full refresh complete (cache cleared, {accessible}/{len(remote_hosts)} hosts accessible)")

    def _refresh_quick(self):
        """Quick refresh without SSH."""
        with console.status("[cyan]Force refreshing context...[/cyan]", spinner="dots"):
            self.repl.context_manager.discover_environment(scan_remote=False, force=True)
        print_success("Context refreshed (cache cleared)")
        console.print("[dim]Use /refresh --full to also scan remote hosts via SSH[/dim]")

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
                status = "✅ Valid" if info['valid'] else "❌ Expired"
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
            inventory = context.get('inventory', {})
            remote_hosts = context.get('remote_hosts', {})

            console.print("\n[bold]🖥️ Current Context[/bold]")
            console.print(f"  Local: {local.get('hostname', 'unknown')} ({local.get('os', 'unknown')})")
            console.print(f"  Inventory: {len(inventory)} hosts")

            if remote_hosts:
                accessible = sum(1 for h in remote_hosts.values() if h.get('accessible'))
                console.print(f"  Remote: {accessible}/{len(remote_hosts)} accessible\n")

        except Exception as e:
            print_error(f"Failed to get context: {e}")

        return True

    def handle_ssh_info(self) -> bool:
        """Show SSH configuration and available keys."""
        try:
            console.print("\n[bold]🔑 SSH Configuration[/bold]\n")

            if self.repl.credentials.supports_agent():
                agent_keys = self.repl.credentials.get_agent_keys()
                if agent_keys:
                    console.print(f"[green]✅ ssh-agent: {len(agent_keys)} keys loaded[/green]")
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
                console.print("\n[bold]🔒 Permission Capabilities (Cached)[/bold]\n")
                for target, _caps in self.repl.orchestrator.permissions.capabilities_cache.items():
                    console.print(f"[cyan]{target}[/cyan]:")
                    console.print(self.repl.orchestrator.permissions.format_capabilities_summary(target))
                    console.print()
        else:
            # Show permissions for specific host
            target = args[0]
            console.print(f"\n[bold]🔍 Detecting permissions on {target}...[/bold]\n")
            try:
                self.repl.orchestrator.permissions.detect_capabilities(target)
                console.print(self.repl.orchestrator.permissions.format_capabilities_summary(target))
            except Exception as e:
                print_error(f"{e}")
        return True
