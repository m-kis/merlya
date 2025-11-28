"""
Handles viewing and searching inventory.
"""
from typing import List, Tuple

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_warning


class InventoryViewer:
    """Handles listing, showing, and searching hosts."""

    def __init__(self, repo):
        self.repo = repo

    def _parse_limit_arg(
        self, args: List[str], default_limit: int
    ) -> Tuple[int, List[str], bool]:
        """Parse --limit argument from args list.

        Returns:
            Tuple of (limit, remaining_args, has_error).
            If has_error is True, an error message was printed and caller should return early.
        """
        limit = default_limit
        remaining_args = []
        i = 0
        while i < len(args):
            if args[i] == "--limit":
                if i + 1 >= len(args):
                    print_error("Missing value for --limit")
                    return (0, [], True)
                try:
                    limit = int(args[i + 1])
                    if limit < 1:
                        print_error("Limit must be a positive integer")
                        return (0, [], True)
                except ValueError:
                    print_error(f"Invalid limit value: {args[i + 1]}")
                    return (0, [], True)
                i += 2
            else:
                remaining_args.append(args[i])
                i += 1
        return (limit, remaining_args, False)

    def handle_list(self, args: List[str]) -> bool:
        """Handle /inventory list."""
        sources = self.repo.list_sources()

        if not sources:
            print_warning("No inventory sources configured")
            console.print("[dim]Use /inventory add <file> to import hosts[/dim]")
            return True

        table = Table(title="Inventory Sources")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Hosts", style="yellow")
        table.add_column("Added", style="dim")

        for source in sources:
            # Safely extract date portion
            created_at = source.get("created_at") or ""
            date_str = created_at[:10] if len(created_at) >= 10 else created_at or "-"
            table.add_row(
                source["name"],
                source["source_type"],
                str(source["host_count"]),
                date_str,
            )

        console.print(table)
        return True

    def handle_show(self, args: List[str]) -> bool:
        """Handle /inventory show [source] [--limit N]."""
        limit, remaining_args, has_error = self._parse_limit_arg(args, default_limit=100)
        if has_error:
            return True

        source_name = remaining_args[0] if remaining_args else None
        source_id = None

        if source_name:
            source = self.repo.get_source(source_name)
            if not source:
                print_error(f"Source not found: {source_name}")
                return True
            source_id = source["id"]

        # Request one extra row to detect truncation
        hosts = self.repo.search_hosts(source_id=source_id, limit=limit + 1)

        if not hosts:
            print_warning("No hosts found")
            return True

        # Detect truncation and trim to display limit
        truncated = len(hosts) > limit
        if truncated:
            hosts = hosts[:limit]

        title = f"Hosts from '{source_name}'" if source_name else "All Hosts"
        if truncated:
            title_suffix = f"(showing first {limit} of >{limit})"
        else:
            title_suffix = f"({len(hosts)} total)"

        table = Table(title=f"{title} {title_suffix}")
        table.add_column("Hostname", style="cyan")
        table.add_column("IP", style="green")
        table.add_column("Environment", style="yellow")
        table.add_column("Status", style="magenta")

        for host in hosts:
            status_color = {
                "online": "green",
                "offline": "red",
                "unknown": "dim",
            }.get(host.get("status", "unknown"), "dim")

            table.add_row(
                host["hostname"],
                host.get("ip_address") or "-",
                host.get("environment") or "-",
                f"[{status_color}]{host.get('status', 'unknown')}[/{status_color}]",
            )

        console.print(table)
        if truncated:
            console.print(f"[yellow]Showing first {limit} of >{limit} matching hosts. Use --limit N to adjust.[/yellow]")
        console.print("[dim]Use @hostname to reference these hosts[/dim]")
        return True

    def handle_search(self, args: List[str]) -> bool:
        """Handle /inventory search <pattern> [--limit N]."""
        if not args:
            print_error("Usage: /inventory search <pattern> [--limit N]")
            return True

        limit, remaining_args, has_error = self._parse_limit_arg(args, default_limit=50)
        if has_error:
            return True

        if not remaining_args:
            print_error("Usage: /inventory search <pattern> [--limit N]")
            return True

        pattern = " ".join(remaining_args)

        # Request one extra row to detect truncation
        hosts = self.repo.search_hosts(pattern=pattern, limit=limit + 1)

        if not hosts:
            print_warning(f"No hosts matching '{pattern}'")
            return True

        # Detect truncation and trim to display limit
        truncated = len(hosts) > limit
        if truncated:
            hosts = hosts[:limit]

        if truncated:
            title = f"Search results for '{pattern}' (showing first {limit} of >{limit})"
        else:
            title = f"Search results for '{pattern}' ({len(hosts)} found)"

        table = Table(title=title)
        table.add_column("Hostname", style="cyan")
        table.add_column("IP", style="green")
        table.add_column("Environment", style="yellow")
        table.add_column("Groups", style="magenta")

        for host in hosts:
            groups = host.get("groups", [])
            groups_str = ", ".join(groups[:2]) if groups else "-"
            if len(groups) > 2:
                groups_str += f" +{len(groups) - 2}"

            table.add_row(
                host["hostname"],
                host.get("ip_address") or "-",
                host.get("environment") or "-",
                groups_str,
            )

        console.print(table)
        if truncated:
            console.print(f"[yellow]Showing first {limit} of >{limit} matching hosts. Use --limit N to adjust.[/yellow]")
        return True

    def handle_stats(self, args: List[str]) -> bool:
        """Handle /inventory stats."""
        stats = self.repo.get_stats()

        console.print("\n[bold cyan]Inventory Statistics[/bold cyan]\n")
        console.print(f"  Total hosts: [green]{stats.get('total_hosts', 0)}[/green]")

        if stats.get("by_environment"):
            console.print("\n  By environment:")
            for env, count in sorted(stats["by_environment"].items()):
                console.print(f"    {env}: {count}")

        if stats.get("by_source"):
            console.print("\n  By source:")
            for source, count in sorted(stats["by_source"].items()):
                console.print(f"    {source}: {count}")

        console.print(f"\n  Relations: {stats.get('total_relations', 0)} ({stats.get('validated_relations', 0)} validated)")
        console.print(f"  Cached scans: {stats.get('cached_scans', 0)}")

        return True
