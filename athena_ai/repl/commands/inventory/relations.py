"""
Handles relation management commands.
"""
import logging
from typing import List

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning

logger = logging.getLogger(__name__)


class RelationsHandler:
    """Handles host relations."""

    def __init__(self, repo):
        self.repo = repo
        self._classifier = None

    @property
    def classifier(self):
        """Lazy load classifier."""
        if self._classifier is None:
            from athena_ai.inventory.relation_classifier import get_relation_classifier
            self._classifier = get_relation_classifier()
        return self._classifier

    def handle_relations(self, args: List[str]) -> bool:
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
        try:
            suggestions = self.classifier.suggest_relations(hosts, existing)
        except Exception as e:
            logger.debug("Classifier error while suggesting relations: %s", e, exc_info=True)
            print_error("Failed to analyze relations. Please try again later.")
            return True

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

        displayed_count = min(len(suggestions), 15)
        for i, s in enumerate(suggestions[:displayed_count], 1):
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
            # Validate all tokens first and provide clear feedback
            tokens = [x.strip() for x in choice.split(",") if x.strip()]
            if not tokens:
                print_warning("No relations saved")
                return True

            invalid_tokens = [t for t in tokens if not t.isdigit()]
            if invalid_tokens:
                print_error(f"Invalid input: {', '.join(invalid_tokens)}")
                return True

            indices = [int(t) - 1 for t in tokens]

            # Validate indices against displayed_count (not total_count)
            invalid_indices = [i + 1 for i in indices if not (0 <= i < displayed_count)]
            if invalid_indices:
                print_error(f"Invalid selection(s): {', '.join(map(str, invalid_indices))}. Choose from 1-{displayed_count}.")
                return True

        # Build list of relations to save
        relations_to_save = [
            {
                "source_hostname": suggestions[i].source_hostname,
                "target_hostname": suggestions[i].target_hostname,
                "relation_type": suggestions[i].relation_type,
                "confidence": suggestions[i].confidence,
                "validated": True,
                "metadata": suggestions[i].metadata,
            }
            for i in indices
        ]

        # Save relations atomically with error handling
        try:
            saved = self.repo.add_relations_batch(relations_to_save)
            print_success(f"Saved {saved} relations")
        except Exception as e:
            logger.error(
                "Failed to save relations: %s (attempted %d relations)",
                e,
                len(relations_to_save),
                exc_info=True,
            )
            print_error(f"Failed to save relations: {e}")
            return False

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
                rel.get("relation_type", "?"),
                f"{rel.get('confidence', 1.0):.0%}",
            )

        console.print(table)
        return True
