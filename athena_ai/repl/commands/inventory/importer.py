"""
Handles inventory import commands.
"""
from pathlib import Path
from typing import List

from rich.table import Table

from athena_ai.core.exceptions import PersistenceError
from athena_ai.memory.persistence.repositories import HostData
from athena_ai.repl.ui import console, print_error, print_success, print_warning
from athena_ai.utils.logger import logger


class InventoryImporter:
    """Handles importing hosts."""

    def __init__(self, repo):
        self.repo = repo
        self._parser = None

    @property
    def parser(self):
        """Lazy load parser."""
        if self._parser is None:
            from athena_ai.inventory.parser import get_inventory_parser
            self._parser = get_inventory_parser()
        return self._parser

    def handle_add(self, args: List[str]) -> bool:
        """Handle /inventory add <file>."""
        if not args:
            print_error("Usage: /inventory add <file_path>")
            return True

        file_path = " ".join(args)
        path = Path(file_path).expanduser()

        if not path.exists():
            print_error(f"File not found: {file_path}")
            return True

        if not path.is_file():
            print_error(f"Path is not a file: {file_path}")
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

        # Convert parsed hosts to HostData for bulk import
        host_data_list = [
            HostData(
                hostname=host.hostname,
                ip_address=host.ip_address,
                aliases=host.aliases,
                environment=host.environment,
                groups=host.groups,
                role=host.role,
                service=host.service,
                ssh_port=host.ssh_port,
                metadata=host.metadata,
            )
            for host in result.hosts
        ]

        # Add hosts in a single transaction (all-or-nothing)
        try:
            added = self.repo.bulk_add_hosts(
                hosts=host_data_list,
                source_id=source_id,
                changed_by="user",
            )
        except PersistenceError as e:
            # Transaction was rolled back, no partial data persisted
            logger.error(f"Host import failed: {e.reason}", exc_info=True)
            print_error(f"Import failed: {e.reason}")
            console.print(
                f"[dim]Attempted {e.details.get('hosts_attempted', '?')} hosts, "
                f"failed after {e.details.get('hosts_before_failure', '?')}[/dim]"
            )
            # Clean up the source since no hosts were added
            try:
                self.repo.delete_source(source_name)
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to clean up source '%s' after import failure: %s",
                    source_name,
                    cleanup_err,
                    exc_info=True,
                )
            return False

        # Update source host count
        self.repo.update_source_host_count(source_id, added)

        print_success(f"Imported {added} hosts from '{source_name}'")
        console.print("[dim]Use @hostname to reference these hosts in prompts[/dim]")

        return True
