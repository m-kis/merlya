"""
Display Manager for Merlya.
Centralizes all UI/UX logic to ensure a clean, production-ready output.
"""
import threading
from contextlib import contextmanager
from typing import Any, Generator, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.theme import Theme

# Custom theme for semantic coloring
merlya_theme = Theme({
    "info": "dim cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "command": "bold blue",
    "thinking": "italic dim white",
    "result": "white",
    "progress": "cyan",
})


class DisplayManager:
    """
    Manages all console output with strict separation of concerns.
    Thread-safe singleton pattern to ensure consistent access.

    Features:
    - Spinners for long-running operations
    - Progress bars for batch operations
    - Consistent styling across the application
    """

    _instance: Optional["DisplayManager"] = None
    _lock = threading.Lock()

    console: Console
    live: Optional[Live]
    _spinner_active: bool
    _spinner_lock: threading.Lock
    _current_status: Optional[Any]

    def __new__(cls) -> "DisplayManager":
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking pattern
                if cls._instance is None:
                    cls._instance = super(DisplayManager, cls).__new__(cls)
                    cls._instance.console = Console(theme=merlya_theme)
                    cls._instance.live = None
                    cls._instance._spinner_active = False
                    cls._instance._spinner_lock = threading.Lock()
                    cls._instance._current_status = None
        return cls._instance

    def show_welcome(self, env: str):
        """Show welcome banner."""
        self.console.print(Panel.fit(
            f"[bold blue]Merlya CLI[/bold blue]\n[dim]Environment: {env}[/dim]",
            border_style="blue"
        ))

    @contextmanager
    def spinner(
        self,
        message: str,
        spinner_type: str = "dots"
    ) -> Generator[Any, None, None]:
        """
        Context manager for spinner display during long operations.

        Thread-safe: handles concurrent access and nested spinners gracefully.
        For nested spinners, silently yields without printing to avoid
        message duplication like "🧠 Processing...🧠 Connecting".

        Usage:
            with display.spinner("Connecting to host..."):
                # long operation

        Args:
            message: Status message to display
            spinner_type: Type of spinner animation (dots, line, arc, etc.)
        """
        # Thread-safe check and set
        with self._spinner_lock:
            if self._spinner_active:
                # Nested spinner - silently yield to avoid message duplication
                # The outer spinner will be updated by StatusManager.update_host_operation
                yield None
                return
            self._spinner_active = True

        try:
            with self.console.status(
                f"[bold blue]{message}[/bold blue]",
                spinner=spinner_type
            ) as status:
                self._current_status = status
                yield status
        finally:
            with self._spinner_lock:
                self._spinner_active = False
                self._current_status = None

    @contextmanager
    def progress_bar(
        self,
        description: str = "Processing",
        total: Optional[int] = None,
        show_speed: bool = False
    ) -> Generator[Progress, None, None]:
        """
        Context manager for progress bar display.

        Usage:
            with display.progress_bar("Scanning hosts", total=10) as progress:
                task = progress.add_task("Scanning", total=10)
                for host in hosts:
                    # scan host
                    progress.advance(task)

        Args:
            description: Progress description
            total: Total items (None for indeterminate)
            show_speed: Show items/second
        """
        columns = [
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ]

        with Progress(*columns, console=self.console) as progress:
            yield progress

    def create_progress(self) -> Progress:
        """
        Create a Progress instance for manual control.

        Returns:
            Progress instance configured with Merlya styling
        """
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console
        )

    def start_thinking(self, message: str = "Thinking..."):
        """Start a spinner for long-running tasks (legacy method)."""
        if self._spinner_active:
            return

        self._spinner_active = True
        self.console.print(f"[thinking]🧠 {message}[/thinking]")

    def stop_thinking(self):
        """Stop the spinner (legacy method)."""
        self._spinner_active = False

    def show_command(self, target: str, command: str):
        """Show a command being executed."""
        self.console.print(f"[command]⚡ Executing on {target}:[/command] {command}")

    def show_result(self, content: Any, title: Optional[str] = None) -> None:
        """Show the final result of an operation."""
        renderable: Any
        if isinstance(content, str):
            # Try to parse as markdown if it looks like it
            if "\n" in content or "#" in content or "*" in content:
                renderable = Markdown(content)
            else:
                renderable = content
        else:
            renderable = str(content)

        if title:
            self.console.print(Panel(renderable, title=title, border_style="green"))
        else:
            self.console.print(renderable)

    def show_error(self, message: str, details: Optional[str] = None) -> None:
        """Show an error message."""
        self.console.print(f"[error]❌ {message}[/error]")
        if details:
            self.console.print(f"[dim]{details}[/dim]")

    def show_success(self, message: str) -> None:
        """Show a success message."""
        self.console.print(f"[success]✅ {message}[/success]")

    def show_warning(self, message: str) -> None:
        """Show a warning message."""
        self.console.print(f"[warning]⚠️  {message}[/warning]")

    def show_info(self, message: str) -> None:
        """Show an info message."""
        self.console.print(f"[info]ℹ️  {message}[/info]")

    def show_log(self, message: str, level: str = "INFO"):
        """Show a log message."""
        if level == "ERROR":
            style = "error"
        elif level == "WARNING":
            style = "warning"
        else:
            style = "info"

        self.console.print(f"[{style}]{message}[/{style}]")

    def show_step(
        self,
        step_num: int,
        total: int,
        description: str,
        status: str = "running"
    ):
        """
        Show execution step with status.

        Args:
            step_num: Step number
            total: Total steps
            description: Step description
            status: Status (pending, running, completed, failed, skipped)
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

    def update_spinner(self, message: str) -> None:
        """Update the current spinner message."""
        if self._current_status:
            self._current_status.update(f"[bold blue]{message}[/bold blue]")

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None


# Global instance
display = DisplayManager()


def get_display_manager() -> DisplayManager:
    """Get the global DisplayManager instance."""
    return display


def reset_display_manager() -> None:
    """Reset the global DisplayManager (for testing)."""
    global display
    DisplayManager.reset_instance()
    display = DisplayManager()


# Convenience functions for quick access
@contextmanager
def spinner(message: str) -> Generator[Any, None, None]:
    """Convenience function for spinner context manager."""
    with display.spinner(message) as s:
        yield s


@contextmanager
def progress_bar(
    description: str = "Processing",
    total: Optional[int] = None
) -> Generator[Progress, None, None]:
    """Convenience function for progress bar context manager."""
    with display.progress_bar(description, total) as p:
        yield p
