"""
Display Manager for Athena.
Centralizes all UI/UX logic to ensure a clean, production-ready output.
"""
from typing import Optional, Any
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.theme import Theme
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
import threading
import time

# Custom theme for semantic coloring
athena_theme = Theme({
    "info": "dim cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "command": "bold blue",
    "thinking": "italic dim white",
    "result": "white",
})

class DisplayManager:
    """
    Manages all console output with strict separation of concerns.
    Singleton pattern to ensure consistent access.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DisplayManager, cls).__new__(cls)
            cls._instance.console = Console(theme=athena_theme)
            cls._instance.live = None
            cls._instance._spinner_active = False
        return cls._instance

    def show_welcome(self, env: str):
        """Show welcome banner."""
        self.console.print(Panel.fit(
            f"[bold blue]Athena CLI[/bold blue]\n[dim]Environment: {env}[/dim]",
            border_style="blue"
        ))

    def start_thinking(self, message: str = "Thinking..."):
        """Start a spinner for long-running tasks."""
        if self._spinner_active:
            return
            
        self._spinner_active = True
        # We use a simple status for now, can be upgraded to Live later
        self.console.print(f"[thinking]🧠 {message}[/thinking]")

    def stop_thinking(self):
        """Stop the spinner."""
        self._spinner_active = False
        # In a real Live implementation, we would stop the Live object here

    def show_command(self, target: str, command: str):
        """Show a command being executed."""
        self.console.print(f"[command]⚡ Executing on {target}:[/command] {command}")

    def show_result(self, content: Any, title: str = None):
        """Show the final result of an operation."""
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

    def show_error(self, message: str, details: str = None):
        """Show an error message."""
        self.console.print(f"[error]❌ {message}[/error]")
        if details:
            self.console.print(f"[dim]{details}[/dim]")

    def show_log(self, message: str, level: str = "INFO"):
        """Show a log message (only if verbose/debug, handled by logger config usually)."""
        # This is mostly for explicit user-facing logs
        if level == "ERROR":
            style = "error"
        elif level == "WARNING":
            style = "warning"
        else:
            style = "info"
            
        self.console.print(f"[{style}]{message}[/{style}]")

# Global instance
display = DisplayManager()
