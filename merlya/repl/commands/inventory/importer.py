"""
Handles inventory import commands.
"""
from pathlib import Path
from typing import List

from rich.table import Table

from merlya.core.exceptions import PersistenceError
from merlya.memory.persistence.repositories import HostData
from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.utils.logger import logger


class InventoryImporter:
    """Handles importing hosts."""

    def __init__(self, repo):
        self.repo = repo
        self._parser = None

    @property
    def parser(self):
        """Lazy load parser."""
        if self._parser is None:
            from merlya.inventory.parser import get_inventory_parser
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

        # Handle parse errors with graceful fallback
        if result.errors and not result.hosts:
            # Show errors
            for error in result.errors:
                print_error(error)

            # Offer graceful fallback
            from merlya.inventory.parser.fallback_helper import (
                prompt_fallback_action,
                suggest_format_conversion,
            )

            # Get available formats from parser
            available_formats = self.parser.SUPPORTED_FORMATS

            # Prompt user for action
            selected_format, should_skip_errors = prompt_fallback_action(
                format_type=result.source_type,
                error_message=result.errors[0] if result.errors else "Unknown error",
                available_formats=available_formats,
            )

            if selected_format:
                # Retry with user-specified format
                console.print(f"\n[cyan]Retrying with format: {selected_format}...[/cyan]")
                result = self.parser.parse(str(path), format_hint=selected_format)

                # Check if retry succeeded
                if result.errors:
                    for error in result.errors:
                        print_error(error)

                if not result.hosts:
                    suggest_format_conversion(
                        content=path.read_text(errors="replace"),
                        detected_format=selected_format,
                    )
                    return True

            elif should_skip_errors:
                # User chose to skip errors - this is handled by parsers
                # that support lenient parsing (most do)
                console.print("[yellow]Note: Current parser doesn't support skipping errors[/yellow]")
                console.print("[yellow]Please fix the file format and retry[/yellow]")
                return True
            else:
                # User aborted or chose export help
                return True

        # Show non-fatal errors and warnings
        if result.errors and result.hosts:
            for error in result.errors:
                print_warning(f"Non-fatal error: {error}")

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
            # Defensively access error details
            details = getattr(e, "details", {})
            if not isinstance(details, dict):
                details = {}
            console.print(
                f"[dim]Attempted {details.get('hosts_attempted', '?')} hosts, "
                f"failed after {details.get('hosts_before_failure', '?')}[/dim]"
            )
            # Clean up the source since no hosts were added
            try:
                self.repo.delete_source(source_id)
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to clean up source '%s' (id=%s) after import failure: %s",
                    source_name,
                    source_id,
                    cleanup_err,
                    exc_info=True,
                )
            return True

        # Update source host count
        try:
            self.repo.update_source_host_count(source_id, added)
        except PersistenceError as e:
            logger.warning(
                "Failed to update source host count for source_id %s: %s",
                source_id,
                e.reason,
                exc_info=True,
            )
            # Hosts were added successfully, so we still report success
            # but log the inconsistency for monitoring

        print_success(f"Imported {added} hosts from '{source_name}'")
        console.print("[dim]Use @hostname to reference these hosts in prompts[/dim]")

        # CRITICAL: Invalidate HostRegistry cache so new hosts are immediately available
        self._invalidate_host_registry()

        return True

    def _invalidate_host_registry(self) -> None:
        """Invalidate HostRegistry cache after bulk import."""
        try:
            from merlya.context.host_registry import get_host_registry
            registry = get_host_registry()
            registry.invalidate_cache()
            logger.info("✅ HostRegistry cache invalidated after import")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"⚠️ Failed to invalidate HostRegistry: {e}")
