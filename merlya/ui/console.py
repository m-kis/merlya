"""
Merlya UI - Console implementation.

Rich-based console with panels, tables, and markdown.
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from merlya.core.types import CheckStatus

# Custom theme
MERLYA_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "red bold",
        "success": "green",
        "muted": "dim",
        "highlight": "magenta",
    }
)


class ConsoleUI:
    """
    Console user interface.

    Provides rich formatting for output.
    """

    def __init__(self, theme: Theme | None = None) -> None:
        """Initialize console."""
        self.console = Console(theme=theme or MERLYA_THEME)

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Print to console."""
        self.console.print(*args, **kwargs)

    def markdown(self, text: str) -> None:
        """Render markdown text."""
        self.console.print(Markdown(text))

    def panel(self, content: str, title: str | None = None, style: str = "info") -> None:
        """Display a panel."""
        self.console.print(Panel(content, title=title, border_style=style))

    def success(self, message: str) -> None:
        """Display success message."""
        self.console.print(f"[success]{message}[/success]")

    def error(self, message: str) -> None:
        """Display error message."""
        self.console.print(f"[error]{message}[/error]")

    def warning(self, message: str) -> None:
        """Display warning message."""
        self.console.print(f"[warning]{message}[/warning]")

    def info(self, message: str) -> None:
        """Display info message."""
        self.console.print(f"[info]{message}[/info]")

    def muted(self, message: str) -> None:
        """Display muted message."""
        self.console.print(f"[muted]{message}[/muted]")

    def newline(self) -> None:
        """Print empty line."""
        self.console.print()

    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        title: str | None = None,
    ) -> None:
        """Display a table."""
        table = Table(title=title, show_header=True, header_style="bold")

        for header in headers:
            table.add_column(header)

        for row in rows:
            table.add_row(*row)

        self.console.print(table)

    def health_status(self, _name: str, status: CheckStatus, message: str) -> None:
        """Display a health check status."""
        icons = {
            CheckStatus.OK: "[green]✅[/green]",
            CheckStatus.WARNING: "[yellow]⚠️[/yellow]",
            CheckStatus.ERROR: "[red]❌[/red]",
            CheckStatus.DISABLED: "[dim]⊘[/dim]",
        }
        icon = icons.get(status, "❓")
        self.console.print(f"  {icon} {message}")

    async def prompt(self, message: str, default: str = "") -> str:
        """Prompt for input (async-safe)."""
        session: PromptSession[str] = PromptSession()
        result = await session.prompt_async(f"{message}: ", default=default)
        return result.strip()

    async def prompt_secret(self, message: str) -> str:
        """Prompt for secret input (hidden, async-safe)."""
        session: PromptSession[str] = PromptSession()
        result = await session.prompt_async(f"{message}: ", is_password=True)
        return result.strip()

    async def prompt_confirm(self, message: str, default: bool = False) -> bool:
        """Prompt for yes/no confirmation (async-safe)."""
        suffix = " [Y/n]" if default else " [y/N]"
        session: PromptSession[str] = PromptSession()
        result = await session.prompt_async(f"{message}{suffix}: ")
        result = result.strip().lower()

        if not result:
            return default

        return result in ("y", "yes", "oui", "o")

    async def prompt_choice(
        self,
        message: str,
        choices: list[str],
        default: str | None = None,
    ) -> str:
        """Prompt for choice from list (async-safe)."""
        session: PromptSession[str] = PromptSession()
        choices_str = "/".join(choices)
        default_str = f" [{default}]" if default else ""

        result = await session.prompt_async(f"{message} ({choices_str}){default_str}: ")
        result = result.strip()

        if not result and default:
            return default

        if result in choices:
            return result

        # Try numeric selection
        try:
            idx = int(result) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass

        return result
