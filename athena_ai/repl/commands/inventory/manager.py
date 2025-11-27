"""
Handles management commands (remove, export, snapshot).
"""
from pathlib import Path
from typing import List

from athena_ai.repl.ui import console, print_error, print_success, print_warning


class InventoryManager:
    """Handles management of inventory sources and data."""

    def __init__(self, repo):
        self.repo = repo

    def handle_remove(self, args: List[str]) -> bool:
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

    def handle_export(self, args: List[str]) -> bool:
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
                    json.dump(hosts, f, indent=2, default=str, ensure_ascii=False)

            elif ext == ".csv":
                import csv
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        "hostname", "ip_address", "environment", "groups", "role", "service"
                    ])
                    writer.writeheader()
                    for host in hosts:
                        writer.writerow({
                            "hostname": host.get("hostname", ""),
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
                    yaml.dump(hosts, f, default_flow_style=False, allow_unicode=True)

            print_success(f"Exported {len(hosts)} hosts to {file_path}")

        except PermissionError:
            print_error(f"Permission denied: {file_path}")
        except OSError as e:
            print_error(f"Export failed: {e}")

        return True

    def handle_snapshot(self, args: List[str]) -> bool:
        """Handle /inventory snapshot [name]."""
        name = args[0] if args else None

        snapshot_id = self.repo.create_snapshot(name=name)
        stats = self.repo.get_stats()

        print_success(f"Created snapshot #{snapshot_id}")
        console.print(f"  Hosts: {stats['total_hosts']}")
        console.print(f"  Relations: {stats['total_relations']}")

        return True
