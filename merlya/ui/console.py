"""
Merlya UI - Console implementation.

Rich-based console with panels, tables, and markdown.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.theme import Theme

from merlya.core.types import CheckStatus

# Merlya brand color: #40C4E0 (sky blue)
ACCENT_COLOR = "sky_blue2"
MERLYA_THEME = Theme(
    {
        "info": "bold sky_blue2",
        "warning": "gold3",
        "error": "bold red",
        "success": "sky_blue2",  # Use brand blue instead of green
        "muted": "grey58",
        "highlight": "medium_orchid",
        "accent": ACCENT_COLOR,
    }
)


class ConsoleUI:
    """
    Console user interface.

    Provides rich formatting for output.
    """

    def __init__(
        self,
        theme: Theme | None = None,
        auto_confirm: bool = False,
        quiet: bool = False,
    ) -> None:
        """Initialize console."""
        # force_terminal=True enables hyperlinks (OSC 8) for clickable links
        self.console = Console(
            theme=theme or MERLYA_THEME,
            quiet=quiet,
            force_terminal=True,
        )
        self._active_status: Any = None
        self.auto_confirm = auto_confirm
        self.quiet = quiet
        # Mutex to prevent overlapping prompts from parallel agents
        self._prompt_lock = asyncio.Lock()

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Print to console."""
        self.console.print(*args, **kwargs)

    def markdown(self, text: str) -> None:
        """Render markdown text with clickable hyperlinks."""
        self.console.print(Markdown(text, hyperlinks=True))

    def panel(self, content: str, title: str | None = None, style: str = "info") -> None:
        """Display a panel."""
        border_style = style if style in MERLYA_THEME.styles else "accent"
        self.console.print(Panel(content, title=title, border_style=border_style, padding=(1, 2)))

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

    def tool_call(self, host: str, command: str) -> None:
        """Display a tool call being executed (like Claude Code's tool use display)."""
        # Truncate command to 60 chars for display
        cmd_display = command[:60] + "..." if len(command) > 60 else command
        if host == "local":
            self.console.print(f"[dim]🖥️  {cmd_display}[/dim]")
        else:
            self.console.print(f"[dim]🌐 {host}: {cmd_display}[/dim]")

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
        table = Table(
            title=title,
            show_header=True,
            header_style=f"{ACCENT_COLOR} bold",
            box=None,
            padding=(0, 1),
        )

        for header in headers:
            table.add_column(header)

        for row in rows:
            table.add_row(*row)

        self.console.print(table)

    def health_status(self, _name: str, status: CheckStatus, message: str) -> None:
        """Display a health check status."""
        icons = {
            CheckStatus.OK: "[sky_blue2]✅[/sky_blue2]",
            CheckStatus.WARNING: "[yellow]⚠️[/yellow]",
            CheckStatus.ERROR: "[red]❌[/red]",
            CheckStatus.DISABLED: "[dim]⊘[/dim]",
        }
        icon = icons.get(status, "❓")
        self.console.print(f"  {icon} {message}")

    @contextmanager
    def spinner(self, message: str, spinner: str = "dots") -> Any:
        """Show a spinner while executing a task.

        Note: The spinner does not block signals, but network I/O operations
        may not be immediately interruptible. Use timeouts to ensure operations
        can be cancelled within a reasonable time.
        """
        status = self.console.status(f"[{ACCENT_COLOR}]{message}[/{ACCENT_COLOR}]", spinner=spinner)
        self._active_status = status
        try:
            with status:
                yield
        except KeyboardInterrupt:
            # Ensure spinner is stopped on interruption
            with suppress(Exception):
                status.stop()
            self._active_status = None
            # Convert KeyboardInterrupt to CancelledError for proper async handling
            raise asyncio.CancelledError() from None
        except asyncio.CancelledError:
            # Ensure spinner is stopped on cancellation
            with suppress(Exception):
                status.stop()
            self._active_status = None
            raise
        finally:
            # Ensure spinner is stopped before any prompt overlays
            with suppress(Exception):
                status.stop()
            self._active_status = None

    def progress(self, transient: bool = True) -> Progress:
        """
        Create a styled progress bar.

        Usage:
            with ui.progress() as progress:
                task = progress.add_task("Doing work", total=3)
                progress.advance(task)
        """
        return Progress(
            SpinnerColumn(style=ACCENT_COLOR),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None, pulse_style=ACCENT_COLOR),
            TimeElapsedColumn(),
            console=self.console,
            transient=transient,
            expand=True,
        )

    async def prompt(self, message: str, default: str | None = "") -> str:
        """Prompt for input (async-safe with mutex to prevent overlap)."""
        # In auto_confirm/non-interactive mode, return default or raise error
        if self.auto_confirm:
            if default:
                if not self.quiet:
                    self.console.print(f"[muted]{message}: {default} [auto][/muted]")
                return default
            raise RuntimeError(f"Cannot prompt in non-interactive mode: {message}")

        async with self._prompt_lock:
            self._stop_spinner()
            session: PromptSession[str] = PromptSession()
            # prompt_toolkit Document cannot take None defaults
            safe_default = default if default is not None else ""
            try:
                result = await session.prompt_async(f"{message}: ", default=safe_default)
                return result.strip()
            except KeyboardInterrupt:
                # Convert KeyboardInterrupt to CancelledError for proper async handling
                raise asyncio.CancelledError() from None

    async def prompt_secret(self, message: str) -> str:
        """Prompt for secret input (hidden, async-safe with mutex)."""
        # In auto_confirm/non-interactive mode, secrets cannot be prompted
        if self.auto_confirm:
            raise RuntimeError(
                f"Cannot prompt for secret in non-interactive mode: {message}. "
                "Use keyring or environment variables for credentials."
            )

        async with self._prompt_lock:
            self._stop_spinner()
            session: PromptSession[str] = PromptSession()
            try:
                result = await session.prompt_async(f"{message}: ", is_password=True)
                return result.strip()
            except KeyboardInterrupt:
                raise asyncio.CancelledError() from None

    async def prompt_confirm(self, message: str, default: bool = False) -> bool:
        """Prompt for yes/no confirmation (async-safe with mutex)."""
        if self.auto_confirm:
            if not self.quiet:
                self.console.print(f"[muted]{message} [auto-confirmed][/muted]")
            return True

        async with self._prompt_lock:
            self._stop_spinner()
            suffix = " [Y/n]" if default else " [y/N]"
            session: PromptSession[str] = PromptSession()
            try:
                result = await session.prompt_async(f"{message}{suffix}: ")
                result = result.strip().lower()

                if not result:
                    return default

                return result in ("y", "yes", "oui", "o")
            except KeyboardInterrupt:
                raise asyncio.CancelledError() from None

    async def confirm(self, message: str, default: bool = False) -> bool:
        """Alias for prompt_confirm for compatibility."""
        return await self.prompt_confirm(message, default)

    async def prompt_choice(
        self,
        message: str,
        choices: list[str],
        default: str | None = None,
    ) -> str:
        """Prompt for choice from list (async-safe with mutex)."""
        async with self._prompt_lock:
            self._stop_spinner()
            session: PromptSession[str] = PromptSession()
            choices_str = "/".join(choices)
            default_str = f" [{default}]" if default else ""

            try:
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
            except KeyboardInterrupt:
                raise asyncio.CancelledError() from None

    def _stop_spinner(self) -> None:
        """Stop any active spinner before prompting the user."""
        if self._active_status:
            with suppress(Exception):
                self._active_status.stop()
            self._active_status = None

    def welcome_screen(
        self,
        *,
        title: str,
        warning_title: str,
        hero_lines: list[str],
        warning_lines: list[str],
    ) -> None:
        """Render legacy-inspired welcome screen with hero and warning panels."""
        from rich.align import Align
        from rich.panel import Panel

        hero_panel = Panel(
            Align.left("\n".join(hero_lines)),
            title=title,
            border_style="accent",
            padding=(1, 3),
        )

        warning_panel = Panel(
            Align.left("\n".join(warning_lines)),
            title=warning_title,
            border_style="warning",
            padding=(1, 3),
        )

        self.console.print(hero_panel)
        self.console.print()
        self.console.print(warning_panel)
