"""
Smooth, fluid UI feedback for Athena.

Provides real-time progress, status updates, and beautiful terminal output.
"""
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.syntax import Syntax
from rich.table import Table


class SmoothDisplay:
    """
    Provides smooth, fluid display with real-time updates.

    Features:
    - Real-time progress bars
    - Status indicators
    - Live command output
    - Beautiful formatted results
    - Smooth animations
    """

    def __init__(self):
        self.console = Console()
        self._current_status = None

    def show_welcome(self, version: str = "0.1.0"):
        """Show welcome banner."""
        banner = f"""
[bold cyan]
╦  ╦╦╔╗ ╔═╗  ╦╔╗╔╔═╗╦═╗╔═╗
╚╗╔╝║╠╩╗║╣   ║║║║╠╣ ╠╦╝╠═╣
 ╚╝ ╩╚═╝╚═╝  ╩╝╚╝╚  ╩╚═╩ ╩[/bold cyan]

[dim]AI-Powered Infrastructure Orchestration[/dim]
[dim]Version {version}[/dim]
"""
        self.console.print(Panel(banner, border_style="cyan"))

    @contextmanager
    def status(self, message: str, spinner: str = "dots"):
        """
        Context manager for status display.

        Usage:
            with display.status("Processing..."):
                # do work
        """
        with self.console.status(f"[bold blue]{message}[/bold blue]", spinner=spinner) as status:
            self._current_status = status
            try:
                yield status
            finally:
                self._current_status = None

    def show_step(self, step_num: int, total: int, description: str, status: str = "running"):
        """
        Show execution step with status.

        Args:
            step_num: Step number
            total: Total steps
            description: Step description
            status: Status (pending, running, completed, failed)
        """
        icons = {
            "pending": "⏳",
            "running": "▶️ ",
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️ "
        }

        colors = {
            "pending": "dim",
            "running": "bold blue",
            "completed": "bold green",
            "failed": "bold red",
            "skipped": "dim"
        }

        icon = icons.get(status, "•")
        color = colors.get(status, "white")

        self.console.print(
            f"{icon} [{color}]Step {step_num}/{total}:[/{color}] {description}"
        )

    def show_plan_table(self, steps: List[Dict[str, Any]]):
        """
        Show execution plan as formatted table.

        Args:
            steps: List of plan steps
        """
        table = Table(title="📋 Execution Plan", show_header=True, header_style="bold cyan")

        table.add_column("Step", style="cyan", width=6)
        table.add_column("Description", style="white")
        table.add_column("Type", style="magenta", width=12)
        table.add_column("Dependencies", style="dim", width=12)

        for step in steps:
            step_id = str(step["id"])
            desc = step.get("description", "")[:60]

            # Determine type
            if step.get("critical", False):
                step_type = "⚠️  Critical"
            elif step.get("parallelizable", False):
                step_type = "⚡ Parallel"
            else:
                step_type = "▶️  Sequential"

            deps = step.get("dependencies", [])
            deps_str = ", ".join(map(str, deps)) if deps else "-"

            table.add_row(step_id, desc, step_type, deps_str)

        self.console.print(table)

    def show_progress(self, steps: List[Dict[str, Any]]) -> Progress:
        """
        Create and return progress bar for plan execution.

        Args:
            steps: Plan steps

        Returns:
            Progress instance
        """
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console
        )

    def show_command(self, target: str, command: str):
        """
        Show command being executed.

        Args:
            target: Target host
            command: Command string
        """
        self.console.print(
            f"\n[dim]→[/dim] [cyan]{target}[/cyan] [dim]$[/dim] [bold]{command}[/bold]"
        )

    def show_command_output(self, output: str, error: bool = False):
        """
        Show command output.

        Args:
            output: Command output
            error: Whether this is error output
        """
        if error:
            self.console.print(f"[red]{output}[/red]")
        else:
            self.console.print(f"[dim]{output}[/dim]")

    def show_preview_panel(self, title: str, content: str, border_color: str = "cyan"):
        """
        Show preview in a panel.

        Args:
            title: Panel title
            content: Panel content
            border_color: Border color
        """
        self.console.print(Panel(
            content,
            title=title,
            border_style=border_color,
            padding=(1, 2)
        ))

    def show_diff(self, diff_lines: List[str]):
        """
        Show colored diff output.

        Args:
            diff_lines: List of diff lines
        """
        for line in diff_lines:
            if line.startswith('+++') or line.startswith('---'):
                self.console.print(f"[bold cyan]{line}[/bold cyan]")
            elif line.startswith('@@'):
                self.console.print(f"[bold magenta]{line}[/bold magenta]")
            elif line.startswith('+'):
                self.console.print(f"[green]{line}[/green]")
            elif line.startswith('-'):
                self.console.print(f"[red]{line}[/red]")
            else:
                self.console.print(f"[dim]{line}[/dim]")

    def show_success(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Show success message with optional details.

        Args:
            message: Success message
            details: Optional details dict
        """
        content = f"[bold green]✅ {message}[/bold green]"

        if details:
            content += "\n\n"
            for key, value in details.items():
                content += f"  [cyan]{key}:[/cyan] {value}\n"

        self.console.print(Panel(
            content,
            border_style="green",
            padding=(1, 2)
        ))

    def show_error(self, message: str, details: Optional[str] = None):
        """
        Show error message with optional details.

        Args:
            message: Error message
            details: Optional error details
        """
        content = f"[bold red]❌ {message}[/bold red]"

        if details:
            content += f"\n\n[dim]{details}[/dim]"

        self.console.print(Panel(
            content,
            border_style="red",
            padding=(1, 2)
        ))

    def show_warning(self, message: str):
        """
        Show warning message.

        Args:
            message: Warning message
        """
        self.console.print(
            f"[bold yellow]⚠️  {message}[/bold yellow]"
        )

    def show_info(self, message: str):
        """
        Show info message.

        Args:
            message: Info message
        """
        self.console.print(
            f"[bold blue]ℹ️  {message}[/bold blue]"
        )

    def show_code(self, code: str, language: str = "bash", title: Optional[str] = None):
        """
        Show syntax-highlighted code.

        Args:
            code: Code to display
            language: Programming language
            title: Optional title
        """
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)

        if title:
            self.console.print(Panel(
                syntax,
                title=title,
                border_style="cyan"
            ))
        else:
            self.console.print(syntax)

    def show_summary_table(self, data: Dict[str, Any], title: str = "Summary"):
        """
        Show summary as a table.

        Args:
            data: Data to display
            title: Table title
        """
        table = Table(title=title, show_header=False)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")

        for key, value in data.items():
            table.add_row(key, str(value))

        self.console.print(table)

    def clear(self):
        """Clear the console."""
        self.console.clear()

    def print(self, *args, **kwargs):
        """Print to console (passthrough to Rich)."""
        self.console.print(*args, **kwargs)


# Global instance
smooth_display = SmoothDisplay()
