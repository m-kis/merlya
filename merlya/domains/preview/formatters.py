"""
Formatters for rich diff visualization.

Uses Rich library for beautiful terminal output.
"""
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class DiffFormatter:
    """
    Format diffs with colors and styling using Rich.

    Separation of Concerns: Formatting separate from diff logic.
    """

    def __init__(self):
        self.console = Console()

    def format_diff(self, diff_lines: List[str], title: str = "Diff") -> str:
        """
        Format diff with color-coded lines.

        Args:
            diff_lines: List of diff lines
            title: Title for the diff panel

        Returns:
            Formatted diff string
        """
        if not diff_lines:
            return "No changes detected"

        formatted_lines = []

        for line in diff_lines:
            if line.startswith('+++') or line.startswith('---'):
                # File headers
                formatted_lines.append(f"[bold cyan]{line}[/bold cyan]")
            elif line.startswith('@@'):
                # Hunk headers
                formatted_lines.append(f"[bold magenta]{line}[/bold magenta]")
            elif line.startswith('+'):
                # Added lines
                formatted_lines.append(f"[green]{line}[/green]")
            elif line.startswith('-'):
                # Removed lines
                formatted_lines.append(f"[red]{line}[/red]")
            else:
                # Context lines
                formatted_lines.append(f"[dim]{line}[/dim]")

        content = "\n".join(formatted_lines)
        return content

    def format_change_summary(self, summary: dict) -> str:
        """
        Format change summary as a table.

        Args:
            summary: Summary dict from DiffEngine.get_change_summary()

        Returns:
            Formatted summary string
        """
        table = Table(title="Change Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")

        table.add_row("Lines Added", f"[green]+{summary['added_lines']}[/green]")
        table.add_row("Lines Removed", f"[red]-{summary['removed_lines']}[/red]")
        table.add_row("Total Changes", str(summary['total_changes']))
        table.add_row("Old Line Count", str(summary['old_line_count']))
        table.add_row("New Line Count", str(summary['new_line_count']))
        table.add_row("Similarity", f"{summary['similarity']:.1%}")

        # Render to string
        from io import StringIO

        from rich.console import Console as RichConsole
        string_io = StringIO()
        console = RichConsole(file=string_io, force_terminal=True)
        console.print(table)
        return string_io.getvalue()

    def format_side_by_side(
        self,
        old_content: str,
        new_content: str,
        title_old: str = "Before",
        title_new: str = "After"
    ) -> str:
        """
        Format side-by-side comparison.

        Args:
            old_content: Original content
            new_content: New content
            title_old: Title for old content
            title_new: Title for new content

        Returns:
            Formatted side-by-side comparison
        """
        # Create two panels side by side
        old_panel = Panel(
            Text(old_content),
            title=f"[red]{title_old}[/red]",
            border_style="red"
        )

        new_panel = Panel(
            Text(new_content),
            title=f"[green]{title_new}[/green]",
            border_style="green"
        )

        # For simplicity, just stack them vertically
        # True side-by-side would need columns which is more complex
        from io import StringIO

        from rich.console import Console as RichConsole
        string_io = StringIO()
        console = RichConsole(file=string_io, force_terminal=True, width=120)
        console.print(old_panel)
        console.print(new_panel)
        return string_io.getvalue()
