"""
Inventory command handler for Athena REPL.

Commands:
- /inventory add <file> - Import hosts from file
- /inventory list - List all inventory sources
- /inventory show [source] - Show hosts from a source
- /inventory search <pattern> - Search hosts
- /inventory remove <source> - Remove an inventory source
- /inventory export <file> - Export inventory
- /inventory snapshot [name] - Create inventory snapshot
- /inventory relations - Manage host relations
"""

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning

if TYPE_CHECKING:
    from athena_ai.repl.core import AthenaREPL


class InventoryCommandHandler:
    """Handles /inventory commands."""

    def __init__(self, repl: Optional["AthenaREPL"] = None):
        self.repl = repl
        self._parser = None
        self._repo = None
        self._classifier = None

    @property
    def parser(self):
        """Lazy load parser."""
        if self._parser is None:
            from athena_ai.inventory.parser import get_inventory_parser
            self._parser = get_inventory_parser()
        return self._parser

    @property
    def repo(self):
        """Lazy load repository."""
        if self._repo is None:
            from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
            self._repo = get_inventory_repository()
        return self._repo

    @property
    def classifier(self):
        """Lazy load classifier."""
        if self._classifier is None:
            from athena_ai.inventory.relation_classifier import get_relation_classifier
            self._classifier = get_relation_classifier()
        return self._classifier

    def handle(self, args: List[str]) -> bool:
        """
        Handle /inventory command.

        Returns True if command was handled.
        """
        if not args:
            self._show_help()
            return True

        cmd = args[0].lower()
        cmd_args = args[1:]

        handlers = {
            "add": self._handle_add,
            "import": self._handle_add,  # Alias
            "list": self._handle_list,
            "ls": self._handle_list,  # Alias
            "show": self._handle_show,
            "search": self._handle_search,
            "find": self._handle_search,  # Alias
            "remove": self._handle_remove,
            "delete": self._handle_remove,  # Alias
            "rm": self._handle_remove,  # Alias
            "export": self._handle_export,
            "snapshot": self._handle_snapshot,
            "relations": self._handle_relations,
            "stats": self._handle_stats,
            "help": lambda _: self._show_help(),
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(cmd_args)

        print_error(f"Unknown inventory command: {cmd}")
        self._show_help()
        return True

    def _show_help(self) -> bool:
        """Show inventory command help."""
        console.print("\n[bold cyan]Inventory Commands[/bold cyan]\n")
        console.print("  /inventory add <file>       Import hosts from file (CSV, JSON, YAML, etc.)")
        console.print("  /inventory add /etc/hosts   Import from system file")
        console.print("  /inventory list             List all inventory sources")
        console.print("  /inventory show [source]    Show hosts (optionally from specific source)")
        console.print("  /inventory search <pattern> Search hosts by name/IP")
        console.print("  /inventory remove <source>  Remove an inventory source")
        console.print("  /inventory export <file>    Export inventory to file")
        console.print("  /inventory snapshot [name]  Create inventory snapshot")
        console.print("  /inventory relations        Manage host relations")
        console.print("  /inventory stats            Show inventory statistics")
        console.print()
        console.print("[bold]Supported Formats:[/bold]")
        console.print("  CSV, JSON, YAML, TXT, INI (Ansible), /etc/hosts, ~/.ssh/config")
        console.print("  Non-standard formats are parsed using AI")
        console.print()
        console.print("[bold]Host References (@hostname):[/bold]")
        console.print("  Reference hosts in prompts: [cyan]check nginx on @web-prod-01[/cyan]")
        console.print("  Auto-completes from inventory (press Tab)")
        return True

    def _handle_add(self, args: List[str]) -> bool:
        """Handle /inventory add <file>."""
        if not args:
            print_error("Usage: /inventory add <file_path>")
            return True

        file_path = " ".join(args)
        path = Path(file_path).expanduser()

        if not path.exists():
            print_error(f"File not found: {file_path}")
            return True

        console.print(f"\n[cyan]Parsing {path.name}...[/cyan]")

        # Parse the file
        result = self.parser.parse(str(path))

        if result.errors:
            for error in result.errors:
                print_error(error)
            if not result.hosts:
                return True

        if result.warnings:
            for warning in result.warnings:
                print_warning(warning)

        if not result.hosts:
            print_warning("No hosts found in file")
            return True

        # Show preview
        console.print(f"\n[green]Found {len(result.hosts)} hosts[/green] (format: {result.source_type})")
        console.print()

        # Show sample
        table = Table(title="Preview (first 10 hosts)")
        table.add_column("Hostname", style="cyan")
        table.add_column("IP", style="green")
        table.add_column("Environment", style="yellow")
        table.add_column("Groups", style="magenta")

        for host in result.hosts[:10]:
            table.add_row(
                host.hostname,
                host.ip_address or "-",
                host.environment or "-",
                ", ".join(host.groups[:2]) if host.groups else "-",
            )

        if len(result.hosts) > 10:
            table.add_row("...", "...", "...", f"... and {len(result.hosts) - 10} more")

        console.print(table)

        # Confirm import
        try:
            confirm = input("\nImport these hosts? (y/N): ").strip().lower()
            if confirm != "y":
                print_warning("Import cancelled")
                return True
        except (KeyboardInterrupt, EOFError):
            print_warning("\nImport cancelled")
            return True

        # Create source
        source_name = path.stem
        existing_source = self.repo.get_source(source_name)
        if existing_source:
            # Append number to make unique (with safety limit)
            i = 2
            max_attempts = 1000
            while self.repo.get_source(f"{source_name}_{i}") and i < max_attempts:
                i += 1
            if i >= max_attempts:
                print_error(f"Too many sources with name '{source_name}'")
                return True
            source_name = f"{source_name}_{i}"

        source_id = self.repo.add_source(
            name=source_name,
            source_type=result.source_type,
            file_path=str(path.absolute()),
            import_method="manual",
        )

        # Add hosts
        added = 0
        for host in result.hosts:
            try:
                self.repo.add_host(
                    hostname=host.hostname,
                    ip_address=host.ip_address,
                    aliases=host.aliases,
                    environment=host.environment,
                    groups=host.groups,
                    role=host.role,
                    service=host.service,
                    ssh_port=host.ssh_port,
                    source_id=source_id,
                    metadata=host.metadata,
                    changed_by="user",
                )
                added += 1
            except Exception as e:
                print_warning(f"Could not add {host.hostname}: {e}")

        # Update source host count
        self.repo.update_source_host_count(source_id, added)

        print_success(f"Imported {added} hosts from '{source_name}'")
        console.print(f"[dim]Use @hostname to reference these hosts in prompts[/dim]")

        return True

    def _handle_list(self, args: List[str]) -> bool:
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
            # Safely extract date portion (handle None or short strings)
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

    def _handle_show(self, args: List[str]) -> bool:
        """Handle /inventory show [source]."""
        source_name = args[0] if args else None
        source_id = None

        if source_name:
            source = self.repo.get_source(source_name)
            if not source:
                print_error(f"Source not found: {source_name}")
                return True
            source_id = source["id"]

        hosts = self.repo.search_hosts(source_id=source_id, limit=100)

        if not hosts:
            print_warning("No hosts found")
            return True

        title = f"Hosts from '{source_name}'" if source_name else "All Hosts"
        table = Table(title=f"{title} ({len(hosts)} total)")
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
        console.print(f"\n[dim]Use @hostname to reference these hosts[/dim]")
        return True

    def _handle_search(self, args: List[str]) -> bool:
        """Handle /inventory search <pattern>."""
        if not args:
            print_error("Usage: /inventory search <pattern>")
            return True

        pattern = " ".join(args)
        hosts = self.repo.search_hosts(pattern=pattern, limit=50)

        if not hosts:
            print_warning(f"No hosts matching '{pattern}'")
            return True

        table = Table(title=f"Search results for '{pattern}'")
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
        return True

    def _handle_remove(self, args: List[str]) -> bool:
        """Handle /inventory remove <source>."""
        if not args:
            print_error("Usage: /inventory remove <source_name>")
            return True

        source_name = args[0]
        source = self.repo.get_source(source_name)

        if not source:
            print_error(f"Source not found: {source_name}")
            return True

        # Confirm deletion
        host_count = source["host_count"]
        try:
            confirm = input(f"Delete '{source_name}' and its {host_count} hosts? (y/N): ").strip().lower()
            if confirm != "y":
                print_warning("Deletion cancelled")
                return True
        except (KeyboardInterrupt, EOFError):
            print_warning("\nDeletion cancelled")
            return True

        if self.repo.delete_source(source_name):
            print_success(f"Removed inventory source: {source_name}")
        else:
            print_error("Failed to remove source")

        return True

    def _handle_export(self, args: List[str]) -> bool:
        """Handle /inventory export <file>."""
        if not args:
            print_error("Usage: /inventory export <file_path>")
            return True

        file_path = Path(" ".join(args)).expanduser()

        # Determine format from extension
        ext = file_path.suffix.lower()
        if ext not in [".json", ".csv", ".yaml", ".yml"]:
            print_error("Supported export formats: .json, .csv, .yaml")
            return True

        hosts = self.repo.get_all_hosts()
        if not hosts:
            print_warning("No hosts to export")
            return True

        try:
            if ext == ".json":
                import json
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(hosts, f, indent=2, default=str)

            elif ext == ".csv":
                import csv
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        "hostname", "ip_address", "environment", "groups", "role", "service"
                    ])
                    writer.writeheader()
                    for host in hosts:
                        writer.writerow({
                            "hostname": host["hostname"],
                            "ip_address": host.get("ip_address", ""),
                            "environment": host.get("environment", ""),
                            "groups": ",".join(host.get("groups", [])),
                            "role": host.get("role", ""),
                            "service": host.get("service", ""),
                        })

            elif ext in [".yaml", ".yml"]:
                try:
                    import yaml
                except ImportError:
                    print_error("YAML export requires PyYAML: pip install pyyaml")
                    return True
                with open(file_path, "w", encoding="utf-8") as f:
                    yaml.dump(hosts, f, default_flow_style=False)

            print_success(f"Exported {len(hosts)} hosts to {file_path}")

        except Exception as e:
            print_error(f"Export failed: {e}")

        return True

    def _handle_snapshot(self, args: List[str]) -> bool:
        """Handle /inventory snapshot [name]."""
        name = args[0] if args else None

        snapshot_id = self.repo.create_snapshot(name=name)
        stats = self.repo.get_stats()

        print_success(f"Created snapshot #{snapshot_id}")
        console.print(f"  Hosts: {stats['total_hosts']}")
        console.print(f"  Relations: {stats['total_relations']}")

        return True

    def _handle_relations(self, args: List[str]) -> bool:
        """Handle /inventory relations command."""
        if not args or args[0] == "suggest":
            return self._handle_relations_suggest()
        elif args[0] == "list":
            return self._handle_relations_list()
        elif args[0] == "help":
            console.print("\n[bold]Relation Commands:[/bold]")
            console.print("  /inventory relations suggest  Get AI-suggested relations")
            console.print("  /inventory relations list     List validated relations")
            return True
        else:
            print_error(f"Unknown relations command: {args[0]}")
            return True

    def _handle_relations_suggest(self) -> bool:
        """Generate and display relation suggestions."""
        hosts = self.repo.get_all_hosts()

        if len(hosts) < 2:
            print_warning("Need at least 2 hosts to suggest relations")
            return True

        console.print("\n[cyan]Analyzing host relationships...[/cyan]")

        existing = self.repo.get_relations()
        suggestions = self.classifier.suggest_relations(hosts, existing)

        if not suggestions:
            print_warning("No relation suggestions found")
            return True

        table = Table(title="Suggested Host Relations")
        table.add_column("#", style="cyan", width=3)
        table.add_column("Source", style="green")
        table.add_column("→", style="dim", width=3)
        table.add_column("Target", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Confidence", style="magenta", width=10)
        table.add_column("Reason", style="dim")

        for i, s in enumerate(suggestions[:15], 1):
            table.add_row(
                str(i),
                s.source_hostname,
                "→",
                s.target_hostname,
                s.relation_type,
                f"{s.confidence:.0%}",
                s.reason[:35] + "..." if len(s.reason) > 35 else s.reason,
            )

        console.print(table)

        displayed_count = min(len(suggestions), 15)
        total_count = len(suggestions)

        if total_count > displayed_count:
            console.print(f"[dim]... and {total_count - displayed_count} more suggestions[/dim]")

        # Ask for validation with clear options
        if total_count > displayed_count:
            console.print(f"\n[yellow]Enter numbers to accept (1-{displayed_count}), 'all' (all {total_count}), or 'none':[/yellow]")
        else:
            console.print("\n[yellow]Enter numbers to accept (e.g., '1,3,5'), 'all', or 'none':[/yellow]")

        try:
            choice = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print_warning("\nCancelled")
            return True

        if choice == "none" or not choice:
            print_warning("No relations saved")
            return True

        if choice == "all":
            # Accept ALL suggestions, not just displayed ones
            indices = list(range(total_count))
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
            except ValueError:
                print_error("Invalid input")
                return True

        # Save validated relations
        saved = 0
        for i in indices:
            if 0 <= i < len(suggestions):
                s = suggestions[i]
                self.repo.add_relation(
                    source_hostname=s.source_hostname,
                    target_hostname=s.target_hostname,
                    relation_type=s.relation_type,
                    confidence=s.confidence,
                    validated=True,
                    metadata=s.metadata,
                )
                saved += 1

        print_success(f"Saved {saved} relations")
        return True

    def _handle_relations_list(self) -> bool:
        """List validated relations."""
        relations = self.repo.get_relations(validated_only=True)

        if not relations:
            print_warning("No validated relations")
            console.print("[dim]Use /inventory relations suggest to discover relations[/dim]")
            return True

        table = Table(title="Validated Host Relations")
        table.add_column("Source", style="cyan")
        table.add_column("→", style="dim", width=3)
        table.add_column("Target", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Confidence", style="magenta")

        for rel in relations:
            table.add_row(
                rel.get("source_hostname", "?"),
                "→",
                rel.get("target_hostname", "?"),
                rel["relation_type"],
                f"{rel.get('confidence', 1.0):.0%}",
            )

        console.print(table)
        return True

    def _handle_stats(self, args: List[str]) -> bool:
        """Handle /inventory stats."""
        stats = self.repo.get_stats()

        console.print("\n[bold cyan]Inventory Statistics[/bold cyan]\n")
        console.print(f"  Total hosts: [green]{stats['total_hosts']}[/green]")

        if stats.get("by_environment"):
            console.print("\n  By environment:")
            for env, count in sorted(stats["by_environment"].items()):
                console.print(f"    {env}: {count}")

        if stats.get("by_source"):
            console.print("\n  By source:")
            for source, count in sorted(stats["by_source"].items()):
                console.print(f"    {source}: {count}")

        console.print(f"\n  Relations: {stats['total_relations']} ({stats['validated_relations']} validated)")
        console.print(f"  Cached scans: {stats['cached_scans']}")

        return True
